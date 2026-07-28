"""`observability.metrics.get_metrics` — real Postgres round trip. CI-only
(see conftest.requires_postgres).

Every table these queries read is shared across the whole test session,
never truncated between tests (the same situation
`test_evidence_store_postgres.py`'s own docstring already documents for
`evidence_chain`). Rather than asserting absolute counts, every
governance-health test captures `since = datetime.now(UTC)` *immediately
before* seeding its own data — the real windowed-query codepath under
test, scoped tightly enough that shared-table history from other tests
cannot leak in. System-health metrics (current state, never windowed) are
asserted more loosely, by shape/type, for the same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.observability.metrics import get_metrics
from gov_platform.plugins.registry import register_policy, unregister_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.plugin_registration import PluginType
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from gov_platform.schemas.population_policy_binding import PopulationPolicyBindingLifecycleState
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _far_future_since() -> datetime:
    """A window guaranteed to match nothing -- the "empty database" case
    this shared, never-truncated test session can't otherwise produce."""
    return datetime.now(UTC) + timedelta(days=3650)


def test_a_window_matching_nothing_reports_all_zero_governance_metrics_not_an_error(
    db_engine,
) -> None:
    metrics = get_metrics(db_engine, since=_far_future_since())

    assert metrics.governance.verdict_counts_by_status == {}
    assert metrics.governance.finding_counts_by_policy == {}
    assert metrics.governance.population_finding_counts_by_policy == {}
    assert metrics.governance.shadow_disagreement_rate_by_policy == {}


def test_system_health_reflects_current_state(db_engine) -> None:
    metrics = get_metrics(db_engine, since=_far_future_since())

    assert metrics.system.db_reachable is True
    assert metrics.system.db_latency_ms is not None
    assert metrics.system.evidence_chain_latest_sequence_number >= 0
    # Seeded by tests/conftest.py's autouse fixture -- always present.
    assert "PRODUCTION" in metrics.system.plugin_counts.get("ADAPTER", {})


def test_verdict_counts_reflect_a_real_ingested_event(
    api_client: TestClient, synthetic_payload_json: dict[str, object], db_engine
) -> None:
    since = datetime.now(UTC)
    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"

    response = api_client.post("/v1/ingestion/events/synthetic", json=payload)
    assert response.status_code == 201

    metrics = get_metrics(db_engine, since=since)

    assert metrics.governance.verdict_counts_by_status == {"ALLOW": 1}


def test_finding_counts_reflect_a_real_ingested_event(
    api_client: TestClient, credit_scorecard_payload_json: dict[str, object], db_engine
) -> None:
    since = datetime.now(UTC)
    payload = dict(credit_scorecard_payload_json)
    payload["decision_id"] = f"score-{uuid4()}"

    response = api_client.post("/v1/ingestion/events/credit-scorecard", json=payload)
    assert response.status_code == 201

    metrics = get_metrics(db_engine, since=since)

    # credit-scorecard is governed by two families -- both must be
    # counted, matching M4's own policy-plurality guarantee.
    assert metrics.governance.finding_counts_by_policy["direct-attribute-in-inputs"] == {"CLEAR": 1}
    assert metrics.governance.finding_counts_by_policy["high-debt-ratio-gate"] == {"CLEAR": 1}


def test_population_finding_counts_reflect_a_seeded_finding(db_engine) -> None:
    since = datetime.now(UTC)
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"metrics-test-system-{uuid4()}")
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system.id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.FLAGGED,
            metric_values={},
            classification_snapshot={},
            rationale="test",
            evaluated_at=datetime.now(UTC),
        )
        PopulationFindingRepository().create(session, finding, signature=None, signing_key_id=None)
        session.commit()

    metrics = get_metrics(db_engine, since=since)

    assert metrics.governance.population_finding_counts_by_policy["adverse-impact-ratio"] == {
        "FLAGGED": 1
    }


def test_staleness_shows_none_for_a_binding_that_has_never_run(db_engine) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"staleness-test-system-{uuid4()}")
        binding = PopulationPolicyBindingRepository().create(
            session, system_id=system.id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

    metrics = get_metrics(db_engine, since=_far_future_since())

    assert binding.id in metrics.system.population_binding_staleness
    assert metrics.system.population_binding_staleness[binding.id] is None


def test_staleness_shows_a_real_timestamp_for_a_binding_that_has_run(db_engine) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"staleness-test-system-{uuid4()}")
        binding = PopulationPolicyBindingRepository().create(
            session, system_id=system.id, population_policy_id="adverse-impact-ratio"
        )
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system.id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.CLEAR,
            metric_values={},
            classification_snapshot={},
            rationale="test",
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        PopulationFindingRepository().create(session, finding, signature=None, signing_key_id=None)
        session.commit()

    metrics = get_metrics(db_engine, since=_far_future_since())

    assert metrics.system.population_binding_staleness[binding.id] == datetime(
        2026, 1, 2, tzinfo=UTC
    )


def test_an_inactive_binding_is_not_included_in_staleness(db_engine) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"inactive-test-system-{uuid4()}")
        repository = PopulationPolicyBindingRepository()
        binding = repository.create(
            session, system_id=system.id, population_policy_id="adverse-impact-ratio"
        )
        repository.set_lifecycle_state(
            session, binding.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

    metrics = get_metrics(db_engine, since=_far_future_since())

    assert binding.id not in metrics.system.population_binding_staleness


def test_shadow_disagreement_rate_reflects_a_real_disagreement(
    api_client: TestClient, credit_scorecard_payload_json: dict[str, object], db_engine
) -> None:
    since = datetime.now(UTC)

    class _AlwaysFlagsShadowPolicy(Policy):
        policy_id = "direct-attribute-in-inputs"
        version = f"test-metrics-shadow-{uuid4()}"

        def evaluate(self, event: DecisionEvent) -> Finding:
            return Finding(
                finding_id=str(uuid4()),
                decision_event_id=event.event_id,
                policy_id=self.policy_id,
                policy_version=self.version,
                outcome=FindingOutcome.FLAGGED,
                confidence=1.0,
                rationale="test",
                metric_values={},
                evaluated_at=datetime.now(UTC),
            )

    register_policy(_AlwaysFlagsShadowPolicy)
    registration_repository = PluginRegistrationRepository()
    try:
        with Session(db_engine) as session:
            registration = registration_repository.create(
                session,
                plugin_type=PluginType.POLICY,
                plugin_id=_AlwaysFlagsShadowPolicy.policy_id,
                version=_AlwaysFlagsShadowPolicy.version,
            )
            registration_repository.promote(session, registration.id)  # DRAFT -> SHADOW
            session.commit()

        payload = dict(credit_scorecard_payload_json)
        payload["decision_id"] = f"score-{uuid4()}"
        response = api_client.post("/v1/ingestion/events/credit-scorecard", json=payload)
        assert response.status_code == 201
        assert response.json()["status"] == "ALLOW"  # the real, PRODUCTION answer: CLEAR

        metrics = get_metrics(db_engine, since=since)
    finally:
        unregister_policy(_AlwaysFlagsShadowPolicy.policy_id, _AlwaysFlagsShadowPolicy.version)

    # Production said CLEAR, the shadow candidate always says FLAGGED --
    # one comparable pair, one disagreement.
    assert metrics.governance.shadow_disagreement_rate_by_policy["direct-attribute-in-inputs"] == (
        1.0
    )


def test_a_policy_family_with_no_comparable_shadow_pairs_is_absent_not_zero(db_engine) -> None:
    metrics = get_metrics(db_engine, since=_far_future_since())

    # No shadow activity at all in a window matching nothing -- must be
    # absent, not a misleading 0.0 (docs/milestones/M7.md §4.2, point 4).
    assert metrics.governance.shadow_disagreement_rate_by_policy == {}


def test_a_shadow_finding_with_no_matching_production_finding_is_excluded_from_the_rate(
    api_client: TestClient, synthetic_payload_json: dict[str, object], db_engine
) -> None:
    # A shadow_finding whose decision_event_id has no Finding at all for
    # that same policy_id -- the LEFT JOIN's unmatched-row case (real
    # comparable_count == 0), distinct from "no shadow activity in the
    # window at all" above. Constructed directly rather than through a
    # real shadow-policy registration, since the ingestion route only
    # ever evaluates a shadow candidate that shares a policy_id with one
    # of the adapter's actual governing bindings -- there is no HTTP path
    # that produces this specific mismatch, only direct repository
    # insertion can.
    from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
    from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
    from gov_platform.schemas.plugin_registration import PluginType

    since = datetime.now(UTC)
    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"
    response = api_client.post("/v1/ingestion/events/synthetic", json=payload)
    assert response.status_code == 201
    decision_event_id = response.json()["decision_event_id"]

    unrelated_policy_id = f"unrelated-policy-{uuid4()}"
    with Session(db_engine) as session:
        registration_repository = PluginRegistrationRepository()
        registration = registration_repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=unrelated_policy_id, version="0.1.0"
        )
        registration_repository.promote(session, registration.id)  # DRAFT -> SHADOW
        ShadowFindingRepository().create(
            session,
            Finding(
                finding_id=f"find-{uuid4()}",
                decision_event_id=decision_event_id,
                policy_id=unrelated_policy_id,
                policy_version="0.1.0",
                outcome=FindingOutcome.FLAGGED,
                confidence=1.0,
                rationale="test",
                metric_values={},
                evaluated_at=datetime.now(UTC),
            ),
            plugin_registration_id=registration.id,
        )
        session.commit()

    metrics = get_metrics(db_engine, since=since)

    assert unrelated_policy_id not in metrics.governance.shadow_disagreement_rate_by_policy
