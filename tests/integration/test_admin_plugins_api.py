"""Plugin registry Admin API — over real HTTP against a real Postgres.
CI-only (see conftest.requires_postgres). Mirrors
`test_admin_systems_api.py`'s shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from gov_platform.plugins.registry import register_policy, unregister_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding
from tests.conftest import requires_postgres

pytestmark = requires_postgres


class _LifecycleTestPolicy(Policy):
    """Disposable fake, not one of the four real first-party policies --
    those are all seeded straight to PRODUCTION by the session-wide
    fixture (see conftest._seed_plugin_registry), so none of them can
    demonstrate the DRAFT -> SHADOW -> PRODUCTION climb within this test
    session. Registered/unregistered per-test, same pattern as
    tests/unit/plugins/test_registry.py, for the same reason: leaving it
    registered would leak into other tests' route generation.

    `version` includes a fresh uuid, computed once at class-body
    evaluation (module import) time: `plugin_registrations` is never
    truncated between test runs (same posture as `decision_events`,
    `evidence_chain`, etc.), so a fixed version string would collide with
    the row a previous run already inserted the moment this test ran
    twice against the same database.
    """

    policy_id = "test-lifecycle-policy"
    version = f"1.0.0-{uuid4()}"

    def evaluate(self, event: DecisionEvent) -> Finding:
        raise NotImplementedError


@pytest.fixture
def registered_lifecycle_test_policy() -> Iterator[None]:
    register_policy(_LifecycleTestPolicy)
    try:
        yield
    finally:
        unregister_policy(_LifecycleTestPolicy.policy_id, _LifecycleTestPolicy.version)


def test_register_a_known_first_party_adapter_succeeds(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/plugins",
        json={"plugin_type": "ADAPTER", "plugin_id": "synthetic", "version": "0.1.0"},
    )

    # Already registered by the session-wide seeding fixture -- 409, not
    # 201, is the correct proof that registration is idempotent-aware.
    assert response.status_code == 409


def test_register_an_unknown_plugin_id_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/plugins",
        json={"plugin_type": "POLICY", "plugin_id": "no-such-policy", "version": "9.9.9"},
    )

    assert response.status_code == 422
    assert "plugins/bootstrap.py" in response.json()["detail"]


def test_register_an_unknown_adapter_version_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/plugins",
        json={"plugin_type": "ADAPTER", "plugin_id": "synthetic", "version": "99.0.0"},
    )

    assert response.status_code == 422


def test_list_plugins_includes_the_seeded_first_party_ones(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/plugins")

    assert response.status_code == 200
    plugin_ids = {(p["plugin_type"], p["plugin_id"]) for p in response.json()}
    assert ("ADAPTER", "synthetic") in plugin_ids
    assert ("ADAPTER", "credit-scorecard") in plugin_ids
    assert ("POLICY", "always-allow") in plugin_ids
    assert ("POLICY", "direct-attribute-in-inputs") in plugin_ids


def test_get_unknown_plugin_registration_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/plugins/does-not-exist")

    assert response.status_code == 404


def test_get_a_registered_plugin_by_id(api_client: TestClient) -> None:
    registrations = api_client.get("/v1/admin/plugins").json()
    synthetic = next(r for r in registrations if r["plugin_id"] == "synthetic")

    response = api_client.get(f"/v1/admin/plugins/{synthetic['id']}")

    assert response.status_code == 200
    assert response.json()["plugin_id"] == "synthetic"


def test_promoting_unknown_registration_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/plugins/does-not-exist/promote")

    assert response.status_code == 404


def test_promoting_an_already_production_registration_is_422(api_client: TestClient) -> None:
    registrations = api_client.get("/v1/admin/plugins").json()
    synthetic = next(r for r in registrations if r["plugin_id"] == "synthetic")
    assert synthetic["lifecycle_state"] == "PRODUCTION"  # seeded that way

    response = api_client.post(f"/v1/admin/plugins/{synthetic['id']}/promote")

    assert response.status_code == 422
    assert "already PRODUCTION" in response.json()["detail"]


def test_full_lifecycle_via_the_api_draft_to_shadow_to_production(
    api_client: TestClient, registered_lifecycle_test_policy: None
) -> None:
    register_response = api_client.post(
        "/v1/admin/plugins",
        json={
            "plugin_type": "POLICY",
            "plugin_id": _LifecycleTestPolicy.policy_id,
            "version": _LifecycleTestPolicy.version,
        },
    )
    assert register_response.status_code == 201
    registration = register_response.json()
    assert registration["lifecycle_state"] == "DRAFT"

    shadow_response = api_client.post(f"/v1/admin/plugins/{registration['id']}/promote")
    assert shadow_response.status_code == 200
    assert shadow_response.json()["lifecycle_state"] == "SHADOW"

    production_response = api_client.post(f"/v1/admin/plugins/{registration['id']}/promote")
    assert production_response.status_code == 200
    assert production_response.json()["lifecycle_state"] == "PRODUCTION"

    final_response = api_client.post(f"/v1/admin/plugins/{registration['id']}/promote")
    assert final_response.status_code == 422
