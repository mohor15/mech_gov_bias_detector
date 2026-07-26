"""Tests for the composition root itself — `create_app`'s wiring and its
global exception handler, which is what stands between an unexpected bug
in any collaborator and a client receiving a raw stack trace (the gap V1
left open by never registering one).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from gov_platform.api.app import create_app
from gov_platform.api.dependencies import get_evidence_store
from gov_platform.audit.evidence_store import EvidenceRecord
from gov_platform.config.settings import Settings
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.verdict import GovernanceVerdict
from tests.conftest import requires_postgres


class _ExplodingEvidenceStore:
    """Test double: simulates an unexpected failure deep in the pipeline.

    M3: `GovernanceEngine` is no longer a shared, overridable app.state
    singleton — each generated ingestion route constructs its own
    per-request policy instance from the plugin registry (see
    `api/ingestion/routes.py`). `EvidenceStore` is still the one shared,
    `Depends`-injected collaborator every successful ingestion reaches,
    so it's the equivalent injection point for "an unexpected failure
    deep in the pipeline" now.
    """

    def append(self, event: DecisionEvent, verdict: GovernanceVerdict) -> EvidenceRecord:
        raise RuntimeError("simulated unexpected failure")


@requires_postgres
def test_unhandled_exception_returns_generic_500_not_a_traceback(
    test_settings: Settings, synthetic_payload_json: dict[str, Any]
) -> None:
    # Needs Postgres: the handler's plugin-registration lookups (is this
    # adapter/policy PRODUCTION?) must succeed before EvidenceStore.append
    # is ever reached for the injected failure to actually fire.
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_evidence_store] = lambda: _ExplodingEvidenceStore()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/v1/ingestion/events/synthetic", json=synthetic_payload_json)

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_create_app_wires_independent_instances() -> None:
    # Two app instances must not share an Evidence Store — this is what
    # makes create_app a real composition root rather than V1's shared
    # module-level globals. Doesn't need a real database: construction is
    # lazy (see EvidenceStore's module docstring), so distinct placeholder
    # URLs are enough to prove non-identity without touching Postgres.
    settings_a = Settings(DATABASE_URL="postgresql+psycopg://unreachable-a:5432/a")
    settings_b = Settings(DATABASE_URL="postgresql+psycopg://unreachable-b:5432/b")

    app_a = create_app(settings=settings_a)
    app_b = create_app(settings=settings_b)

    assert app_a.state.evidence_store is not app_b.state.evidence_store
