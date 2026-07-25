from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gov_platform.api.app import create_app
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.config.settings import Settings
from gov_platform.schemas.decision_event import DecisionEvent


@pytest.fixture
def evidence_db_path(tmp_path: Path) -> Path:
    return tmp_path / "evidence.db"


@pytest.fixture
def evidence_store(evidence_db_path: Path) -> EvidenceStore:
    return EvidenceStore(evidence_db_path)


@pytest.fixture
def test_settings(evidence_db_path: Path) -> Settings:
    return Settings(EVIDENCE_DB_PATH=evidence_db_path)


@pytest.fixture
def api_client(test_settings: Settings) -> TestClient:
    app = create_app(settings=test_settings)
    return TestClient(app)


@pytest.fixture
def make_decision_event() -> Any:
    def _make(**overrides: Any) -> DecisionEvent:
        defaults: dict[str, Any] = {
            "event_id": "evt-001",
            "system_id": "synthetic-scorecard",
            "decision_type": "credit_decision",
            "subject_ref": "subject-001",
            "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
            "ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
            "input_features": {"annual_income": 65000.0},
            "protected_attribute_refs": {},
            "decision_output": {"approved": True},
        }
        defaults.update(overrides)
        return DecisionEvent(**defaults)

    return _make


@pytest.fixture
def synthetic_payload_json() -> dict[str, Any]:
    return {
        "source_event_id": "src-evt-001",
        "source_system": "synthetic-scorecard",
        "decision_type": "credit_decision",
        "subject_reference": "subject-001",
        "occurred_at": "2026-01-01T00:00:00Z",
        "features": {"annual_income": 65000.123456},
        "protected_attributes": {"country": "India"},
        "decision": {"approved": True, "rate": 0.085},
    }
