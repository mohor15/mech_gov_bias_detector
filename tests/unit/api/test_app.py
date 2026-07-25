"""Tests for the composition root itself — `create_app`'s wiring and its
global exception handler, which is what stands between an unexpected bug
in any collaborator and a client receiving a raw stack trace (the gap V1
left open by never registering one).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from gov_platform.api.app import create_app
from gov_platform.api.dependencies import get_governance_engine
from gov_platform.config.settings import Settings
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.verdict import GovernanceVerdict


class _ExplodingGovernanceEngine:
    """Test double: simulates an unexpected failure deep in the pipeline."""

    def govern(self, event: DecisionEvent) -> GovernanceVerdict:
        raise RuntimeError("simulated unexpected failure")


def test_unhandled_exception_returns_generic_500_not_a_traceback(
    test_settings: Settings, synthetic_payload_json: dict[str, Any]
) -> None:
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_governance_engine] = lambda: _ExplodingGovernanceEngine()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/v1/ingestion/events", json=synthetic_payload_json)

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_create_app_wires_independent_instances(tmp_path: Any) -> None:
    # Two app instances must not share an Evidence Store — this is what
    # makes create_app a real composition root rather than V1's shared
    # module-level globals.
    settings_a = Settings(EVIDENCE_DB_PATH=tmp_path / "a.db")
    settings_b = Settings(EVIDENCE_DB_PATH=tmp_path / "b.db")

    app_a = create_app(settings=settings_a)
    app_b = create_app(settings=settings_b)

    assert app_a.state.evidence_store is not app_b.state.evidence_store
