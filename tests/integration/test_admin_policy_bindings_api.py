"""Policy Bindings Admin API — over real HTTP against a real Postgres.
CI-only (see conftest.requires_postgres). Mirrors
`test_admin_plugins_api.py`'s shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gov_platform.adapters.base import Adapter
from gov_platform.plugins.registry import (
    register_adapter,
    register_policy,
    unregister_adapter,
    unregister_policy,
)
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding
from tests.conftest import requires_postgres

pytestmark = requires_postgres


class _FakeBindingPayload(BaseModel):
    event_id: str


def _make_fake_adapter_and_policy() -> tuple[type[Adapter[_FakeBindingPayload]], type[Policy]]:
    """Fresh classes with fresh ids per call, not module-level singletons:
    `policy_bindings` is keyed by `(adapter_id, policy_id)` with no version
    component and is never truncated between tests, so a fixed pair shared
    across every test in this file would collide with whichever earlier
    test created a binding for it first — the same class of bug M4's
    shadow-execution tests hit and fixed the same way (see
    tests/integration/test_shadow_execution_postgres.py)."""

    class _FakeBindingAdapter(Adapter[_FakeBindingPayload]):
        adapter_id = f"test-binding-adapter-{uuid4()}"
        version = "1.0.0"

        def translate(self, raw_payload: _FakeBindingPayload) -> DecisionEvent:
            raise NotImplementedError

    class _FakeBindingPolicy(Policy):
        policy_id = f"test-binding-policy-{uuid4()}"
        version = "1.0.0"

        def evaluate(self, event: DecisionEvent) -> Finding:
            raise NotImplementedError

    return _FakeBindingAdapter, _FakeBindingPolicy


@pytest.fixture
def fake_adapter_and_policy() -> Iterator[tuple[type[Adapter[_FakeBindingPayload]], type[Policy]]]:
    adapter_cls, policy_cls = _make_fake_adapter_and_policy()
    register_adapter(adapter_cls)
    register_policy(policy_cls)
    try:
        yield adapter_cls, policy_cls
    finally:
        unregister_adapter(adapter_cls.adapter_id, adapter_cls.version)
        unregister_policy(policy_cls.policy_id, policy_cls.version)


def test_create_a_binding_for_known_adapter_and_policy_succeeds(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    adapter_cls, policy_cls = fake_adapter_and_policy
    response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": policy_cls.policy_id,
            "severity": "MEDIUM",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["adapter_id"] == adapter_cls.adapter_id
    assert body["policy_id"] == policy_cls.policy_id
    assert body["severity"] == "MEDIUM"
    assert body["lifecycle_state"] == "ACTIVE"


def test_create_a_duplicate_binding_is_409(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    adapter_cls, policy_cls = fake_adapter_and_policy
    payload = {
        "adapter_id": adapter_cls.adapter_id,
        "policy_id": policy_cls.policy_id,
        "severity": "LOW",
    }
    first = api_client.post("/v1/admin/policy-bindings", json=payload)
    assert first.status_code == 201

    second = api_client.post("/v1/admin/policy-bindings", json=payload)
    assert second.status_code == 409


def test_recreating_a_binding_after_deactivation_succeeds_through_the_api(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    """The end-to-end proof for M14's own headline fix
    (`docs/milestones/M8.md` §13.20, `docs/milestones/M14.md` §5.1): this
    exact sequence is what the pre-M14 schema *and* the pre-fix conflict
    check both blocked. Goes through the HTTP layer deliberately, not the
    repository directly -- the original bug lived entirely in this
    endpoint's own conflict check, not in the repository or the schema
    alone. Mirrors `test_admin_population_policy_bindings_api.py`'s own
    M8-era twin exactly."""
    adapter_cls, policy_cls = fake_adapter_and_policy
    payload = {
        "adapter_id": adapter_cls.adapter_id,
        "policy_id": policy_cls.policy_id,
        "severity": "LOW",
    }

    first = api_client.post("/v1/admin/policy-bindings", json=payload)
    assert first.status_code == 201
    binding_id = first.json()["id"]

    deactivate = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/deactivate")
    assert deactivate.status_code == 200

    second = api_client.post("/v1/admin/policy-bindings", json={**payload, "severity": "HIGH"})

    assert second.status_code == 201
    assert second.json()["id"] != binding_id
    assert second.json()["severity"] == "HIGH"
    assert second.json()["lifecycle_state"] == "ACTIVE"


def test_recreating_a_still_active_binding_is_still_409(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    """The conflict check must not become permissive across the board --
    only across `lifecycle_state`: a still-`ACTIVE` binding still blocks
    a duplicate, exactly as before M14."""
    adapter_cls, policy_cls = fake_adapter_and_policy
    payload = {
        "adapter_id": adapter_cls.adapter_id,
        "policy_id": policy_cls.policy_id,
        "severity": "LOW",
    }

    first = api_client.post("/v1/admin/policy-bindings", json=payload)
    assert first.status_code == 201

    second = api_client.post("/v1/admin/policy-bindings", json=payload)

    assert second.status_code == 409


def test_create_with_unknown_adapter_id_is_422(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    _adapter_cls, policy_cls = fake_adapter_and_policy
    response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": "no-such-adapter",
            "policy_id": policy_cls.policy_id,
            "severity": "LOW",
        },
    )

    assert response.status_code == 422
    assert "adapter_id" in response.json()["detail"]


def test_create_with_unknown_policy_id_is_422(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    adapter_cls, _policy_cls = fake_adapter_and_policy
    response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": "no-such-policy",
            "severity": "LOW",
        },
    )

    assert response.status_code == 422
    assert "policy_id" in response.json()["detail"]


def test_list_policy_bindings_includes_the_seeded_first_party_ones(
    api_client: TestClient,
) -> None:
    response = api_client.get("/v1/admin/policy-bindings")

    assert response.status_code == 200
    pairs = {(b["adapter_id"], b["policy_id"]) for b in response.json()}
    assert ("synthetic", "always-allow") in pairs
    assert ("credit-scorecard", "direct-attribute-in-inputs") in pairs
    assert ("credit-scorecard", "high-debt-ratio-gate") in pairs


def test_get_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/policy-bindings/does-not-exist")

    assert response.status_code == 404


def test_get_a_created_binding_by_id(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    adapter_cls, policy_cls = fake_adapter_and_policy
    create_response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": policy_cls.policy_id,
            "severity": "HIGH",
        },
    )
    binding_id = create_response.json()["id"]

    response = api_client.get(f"/v1/admin/policy-bindings/{binding_id}")

    assert response.status_code == 200
    assert response.json()["id"] == binding_id


def test_deactivating_and_reactivating_a_binding(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    adapter_cls, policy_cls = fake_adapter_and_policy
    create_response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": policy_cls.policy_id,
            "severity": "LOW",
        },
    )
    binding_id = create_response.json()["id"]

    deactivate_response = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/deactivate")
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["lifecycle_state"] == "INACTIVE"

    activate_response = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["lifecycle_state"] == "ACTIVE"


def test_activating_an_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/policy-bindings/does-not-exist/activate")

    assert response.status_code == 404


def test_deactivating_an_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/policy-bindings/does-not-exist/deactivate")

    assert response.status_code == 404


def test_activating_an_already_active_binding_is_409(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    """M14 §12.1 option (a): a redundant `activate` is a conflict, never a
    silent 200 no-op -- a newly-created binding is already `ACTIVE`."""
    adapter_cls, policy_cls = fake_adapter_and_policy
    create_response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": policy_cls.policy_id,
            "severity": "LOW",
        },
    )
    binding_id = create_response.json()["id"]

    response = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/activate")

    assert response.status_code == 409


def test_deactivating_an_already_inactive_binding_is_409(
    api_client: TestClient,
    fake_adapter_and_policy: tuple[type[Adapter[_FakeBindingPayload]], type[Policy]],
) -> None:
    """M14 §12.1 option (a): a redundant `deactivate` is a conflict, never
    a silent 200 no-op."""
    adapter_cls, policy_cls = fake_adapter_and_policy
    create_response = api_client.post(
        "/v1/admin/policy-bindings",
        json={
            "adapter_id": adapter_cls.adapter_id,
            "policy_id": policy_cls.policy_id,
            "severity": "LOW",
        },
    )
    binding_id = create_response.json()["id"]
    first_deactivate = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/deactivate")
    assert first_deactivate.status_code == 200

    response = api_client.post(f"/v1/admin/policy-bindings/{binding_id}/deactivate")

    assert response.status_code == 409
