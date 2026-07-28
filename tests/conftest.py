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


@pytest.fixture(scope="session", autouse=True)
def _seed_plugin_registry() -> None:
    """M3: every ingestion route now resolves its governing policy (and
    checks its own adapter's lifecycle state) from `plugin_registrations`
    on every request — see `api/ingestion/routes.py`. That means every
    test exercising a real ingestion route now implicitly depends on the
    four first-party plugins being registered and `PRODUCTION`, the same
    idempotent seeding `plugins.seed_registry`'s CLI performs for a real
    deployment. Folded into test session setup (rather than left as a
    separate manual step, unlike migrations) because it's safe to run
    every time and every ingestion test needs it. No-ops if POSTGRES_URL
    isn't set — tests that don't need Postgres are unaffected, same as
    every other DB-dependent fixture in this file.

    M5: also seeds the equivalent Policy Bindings and `FINANCE` protected-
    attribute rules — ingestion routes now resolve governing policies from
    `policy_bindings`, not `Adapter.governing_policy_ids` (removed), and
    `EvidenceStore`'s resolution path now reads `protected_attribute_rules`,
    not `classification.py`'s static dict. Reuses `plugins.seed_registry`'s
    own functions rather than duplicating the seed data here.

    M6: also seeds `adverse-impact-ratio` to `PRODUCTION` — every test
    exercising `population_engine/run_policies.py` or the Population
    Policy Bindings Admin API depends on that plugin's lifecycle state,
    the same way ingestion tests already depend on the first-party
    adapters/policies. No `PopulationPolicyBinding` is seeded here either
    (see `plugins/seed_registry.py`'s module docstring) — tests that need
    one create their own, against a system they control.
    """
    if POSTGRES_URL is None:
        return

    from sqlalchemy.orm import Session

    from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
    from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
    from gov_platform.db.repositories.protected_attribute_rule import (
        ProtectedAttributeRuleRepository,
    )
    from gov_platform.plugins.bootstrap import bootstrap_plugins
    from gov_platform.plugins.registry import (
        known_adapter_keys,
        known_policy_keys,
        known_population_policy_keys,
    )
    from gov_platform.plugins.seed_registry import (
        seed_finance_protected_attribute_rules,
        seed_first_party_policy_bindings,
        seed_to_production,
    )
    from gov_platform.schemas.plugin_registration import PluginType

    bootstrap_plugins()
    engine = create_db_engine(POSTGRES_URL)
    plugin_repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    protected_attribute_rule_repository = ProtectedAttributeRuleRepository()

    with Session(engine) as session:
        for plugin_id, version in known_adapter_keys():
            seed_to_production(
                session,
                plugin_repository,
                plugin_type=PluginType.ADAPTER,
                plugin_id=plugin_id,
                version=version,
            )
        for plugin_id, version in known_policy_keys():
            seed_to_production(
                session,
                plugin_repository,
                plugin_type=PluginType.POLICY,
                plugin_id=plugin_id,
                version=version,
            )
        for plugin_id, version in known_population_policy_keys():
            seed_to_production(
                session,
                plugin_repository,
                plugin_type=PluginType.POPULATION_POLICY,
                plugin_id=plugin_id,
                version=version,
            )
        seed_first_party_policy_bindings(session, policy_binding_repository)
        seed_finance_protected_attribute_rules(session, protected_attribute_rule_repository)
        session.commit()


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
def seed_finance_decisions(db_engine: Engine) -> Any:
    """M6: population tests need many real `decision_events` rows for one
    system, with specific protected-attribute values and outcomes -- a
    different shape of setup than `make_decision_event` (one in-memory
    `DecisionEvent`) or `evidence_store` (one full governed append).
    Writes directly via the repository layer, the same normalized rows
    `EvidenceStore.append` would produce, without needing a real `Verdict`
    for each one. Registers the System with `domain="FINANCE"` so
    `protected_attribute_rules` resolves `DIRECT` attributes for it (see
    `tests/integration/test_population_window_postgres.py`).

    Returns a callable `(decisions) -> system_id`, where each decision is
    `(protected_attribute_refs, approved, occurred_at)`.
    """
    from datetime import UTC
    from datetime import datetime as _datetime
    from uuid import uuid4 as _uuid4

    from sqlalchemy.orm import Session

    from gov_platform.db.repositories.decision_event import DecisionEventRepository
    from gov_platform.db.repositories.model_version import ModelVersionRepository
    from gov_platform.db.repositories.system import SystemRepository
    from gov_platform.schemas.decision_event import DecisionEvent
    from gov_platform.schemas.model_version import UNSPECIFIED_VERSION

    def _seed(
        decisions: list[tuple[dict[str, str], bool, datetime]], *, domain: str | None = "FINANCE"
    ) -> str:
        system_repository = SystemRepository()
        model_version_repository = ModelVersionRepository()
        decision_event_repository = DecisionEventRepository()

        with Session(db_engine) as session:
            system = system_repository.create(
                session, name=f"population-test-system-{_uuid4()}", domain=domain
            )
            model_version = model_version_repository.get_or_create(
                session, system_id=system.id, version=UNSPECIFIED_VERSION
            )
            for protected_attribute_refs, approved, occurred_at in decisions:
                event = DecisionEvent(
                    event_id=f"pop-evt-{_uuid4()}",
                    system_id=system.name,
                    decision_type="credit_decision",
                    subject_ref=f"subj-{_uuid4()}",
                    occurred_at=occurred_at,
                    ingested_at=_datetime.now(UTC),
                    input_features={"annual_income": 50000.0},
                    protected_attribute_refs=protected_attribute_refs,
                    decision_output={"approved": approved},
                )
                decision_event_repository.create(session, event, model_version_id=model_version.id)
            session.commit()

        return system.id

    return _seed


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
