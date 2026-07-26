from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from gov_platform.api.app import create_app
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.config.settings import Settings
from gov_platform.db.session import create_db_engine
from gov_platform.schemas.decision_event import DecisionEvent

# M1: a real Postgres instance is required for anything that actually
# persists data. This sandbox has none (see docs/milestones/M1.md) — set
# POSTGRES_URL to run these tests locally; CI always sets it. Tests that
# never need a successful write (most of M0's suite: schemas, adapters,
# normalization, policy/governance engines, most of the API composition-root
# and middleware tests) need none of this and are unaffected.
POSTGRES_URL = os.environ.get("POSTGRES_URL")

requires_postgres = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="POSTGRES_URL not set — needs a real Postgres instance; see docs/milestones/M1.md",
)

# A syntactically valid but unreachable placeholder, used only by tests that
# construct a Settings/app instance without ever needing a successful DB
# round trip (SQLAlchemy engines are lazy — see EvidenceStore's docstring).
_PLACEHOLDER_DATABASE_URL = "postgresql+psycopg://unreachable:5432/unreachable"


@pytest.fixture
def postgres_url() -> str:
    """Skips the requesting test if POSTGRES_URL isn't set. Prefer the
    `requires_postgres` marker on integration tests; use this fixture when a
    test needs the URL value itself (e.g. to build an engine)."""
    if POSTGRES_URL is None:
        pytest.skip("POSTGRES_URL not set")
    return POSTGRES_URL


@pytest.fixture
def db_engine(postgres_url: str) -> Engine:
    return create_db_engine(postgres_url)


@pytest.fixture
def evidence_store(db_engine: Engine) -> EvidenceStore:
    return EvidenceStore(db_engine)


@pytest.fixture
def test_settings() -> Settings:
    """Real POSTGRES_URL when available (CI), else an unreachable
    placeholder — safe because Settings/create_app construction never
    connects eagerly. Tests that need a successful persistence round trip
    must also carry `requires_postgres` (or depend on `postgres_url`/
    `db_engine`/`evidence_store`, which skip on their own)."""
    return Settings(DATABASE_URL=POSTGRES_URL or _PLACEHOLDER_DATABASE_URL)


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


@pytest.fixture
def credit_scorecard_payload_json() -> dict[str, Any]:
    """M2: a well-formed payload with protected attributes kept properly
    out of `feature_vector` — the CLEAR case. Tests exercising the
    `FLAGGED` (direct-attribute-leak) path override `feature_vector`
    explicitly."""
    return {
        "decision_id": "score-001",
        "applicant_id": "applicant-001",
        "system_name": "credit-scorecard-prod",
        "scored_at": "2026-01-01T00:00:00Z",
        "feature_vector": {"annual_income": 65000.12, "debt_to_income": 0.31},
        "demographic_indicators": {"race": "Black", "zip_code": "12345"},
        "model_score": 712.5,
        "decision_threshold": 650.0,
        "approved": True,
        "reason_codes": ["R01"],
    }
