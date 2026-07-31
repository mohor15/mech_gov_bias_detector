"""`reporting.compliance_report.get_compliance_report` — real Postgres round
trip. CI-only (see conftest.requires_postgres).

Runs under the ordinary `db_engine` (the app's own restricted
`gov_platform_app` role) -- no elevated credential is needed, unlike
retention's `admin_db_engine` (docs/milestones/M12.md §5.4/§12.8): every
query is a read-only `SELECT`, and `gov_platform_app` already holds
`SELECT` on all five tables this milestone reads.

Every table these queries read is shared across the whole test session,
never truncated between tests -- the same situation
`test_metrics_postgres.py`'s own docstring already documents. Every test
below seeds its own `System` (so `--system-id` filtering isolates it from
other tests' data) and captures a tight `[window_start, window_end)`
immediately around its own seeding action, the same "scope the window
tightly enough that shared-table history can't leak in" discipline
`test_metrics_postgres.py` already established for its own open-ended
`since` windows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.reporting.compliance_report import get_compliance_report
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.human_review import (
    PopulationFindingReviewResolution,
    VerdictReviewResolution,
)
from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from gov_platform.schemas.system import System
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _far_future_window() -> tuple[datetime, datetime]:
    """A window guaranteed to match nothing -- the "empty database" case
    this shared, never-truncated test session can't otherwise produce."""
    start = datetime.now(UTC) + timedelta(days=3650)
    return start, start + timedelta(days=1)


def _create_system(db_engine, *, name_prefix: str = "report-test") -> System:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"{name_prefix}-{uuid4()}")
        session.commit()
    return system


def _seed_verdict(
    db_engine,
    *,
    system: System,
    policy_id: str = "report-test-policy",
    outcome: FindingOutcome = FindingOutcome.CLEAR,
    status: VerdictStatus = VerdictStatus.ALLOW,
    evaluated_at: datetime,
    created_at: datetime,
) -> str:
    """Seeds one `ModelVersion` + `DecisionEvent` + `Finding` + `Verdict`
    under `system`. Returns the new verdict_id."""
    with Session(db_engine) as session:
        model_version = ModelVersionRepository().get_or_create(
            session, system_id=system.id, version=UNSPECIFIED_VERSION
        )
        event_id = f"evt-report-{uuid4()}"
        event = DecisionEvent(
            event_id=event_id,
            system_id=system.name,
            decision_type="credit_decision",
            subject_ref=f"subj-{uuid4()}",
            occurred_at=evaluated_at,
            ingested_at=evaluated_at,
            input_features={},
            protected_attribute_refs={},
            decision_output={"approved": True},
        )
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)

        finding = Finding(
            finding_id=f"find-report-{uuid4()}",
            decision_event_id=event_id,
            policy_id=policy_id,
            policy_version="0.1.0",
            outcome=outcome,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=evaluated_at,
        )
        FindingRepository().create(session, finding)

        verdict_id = f"verdict-report-{uuid4()}"
        verdict = GovernanceVerdict(
            verdict_id=verdict_id,
            decision_event_id=event_id,
            status=status,
            findings=[finding],
            created_at=created_at,
        )
        VerdictRepository().create(session, verdict)
        session.commit()
    return verdict_id


def _seed_population_finding(
    db_engine,
    *,
    system: System,
    population_policy_id: str = "adverse-impact-ratio",
    outcome: PopulationFindingOutcome = PopulationFindingOutcome.CLEAR,
    evaluated_at: datetime,
) -> str:
    population_finding_id = f"pf-report-{uuid4()}"
    with Session(db_engine) as session:
        finding = PopulationFinding(
            population_finding_id=population_finding_id,
            population_policy_id=population_policy_id,
            population_policy_version="0.1.0",
            system_id=system.id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=outcome,
            metric_values={},
            classification_snapshot={},
            rationale="test",
            evaluated_at=evaluated_at,
        )
        PopulationFindingRepository().create(session, finding, signature=None, signing_key_id=None)
        session.commit()
    return population_finding_id


def _resolve_verdict_review(
    db_engine, *, verdict_id: str, resolution: VerdictReviewResolution
) -> None:
    repository = VerdictReviewRepository()
    with Session(db_engine) as session:
        review = repository.create(session, verdict_id)
        session.commit()
    assert review is not None
    with Session(db_engine) as session:
        repository.claim(session, review.id, reviewer="report-tester")
        session.commit()
    with Session(db_engine) as session:
        repository.resolve(
            session,
            review.id,
            reviewer="report-tester",
            resolution=resolution,
            notes="test resolution",
        )
        session.commit()


def _create_open_verdict_review(db_engine, *, verdict_id: str) -> None:
    with Session(db_engine) as session:
        VerdictReviewRepository().create(session, verdict_id)
        session.commit()


def _resolve_population_finding_review(
    db_engine, *, population_finding_id: str, resolution: PopulationFindingReviewResolution
) -> None:
    repository = PopulationFindingReviewRepository()
    with Session(db_engine) as session:
        review = repository.create(session, population_finding_id)
        session.commit()
    assert review is not None
    with Session(db_engine) as session:
        repository.claim(session, review.id, reviewer="report-tester")
        session.commit()
    with Session(db_engine) as session:
        repository.resolve(
            session,
            review.id,
            reviewer="report-tester",
            resolution=resolution,
            notes="test resolution",
        )
        session.commit()


def test_a_window_matching_nothing_reports_all_zero_counts_not_an_error(db_engine) -> None:
    window_start, window_end = _far_future_window()

    report = get_compliance_report(db_engine, window_start=window_start, window_end=window_end)

    assert report.verdicts.by_status == {}
    assert report.findings.by_policy == {}
    assert report.population_findings.by_policy == {}
    assert report.reviews.verdict_reviews_by_resolution == {}
    assert report.reviews.population_finding_reviews_by_resolution == {}
    assert report.window_start == window_start
    assert report.window_end == window_end
    assert report.system_id is None


def test_verdict_and_finding_counts_reflect_a_seeded_verdict_within_the_window(db_engine) -> None:
    system = _create_system(db_engine)
    window_start = datetime.now(UTC)
    _seed_verdict(
        db_engine,
        system=system,
        policy_id="report-test-policy",
        outcome=FindingOutcome.FLAGGED,
        status=VerdictStatus.ESCALATE_FOR_REVIEW,
        evaluated_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.verdicts.by_status == {"ESCALATE_FOR_REVIEW": 1}
    assert report.findings.by_policy == {"report-test-policy": {"FLAGGED": 1}}


def test_a_verdict_created_before_window_start_is_excluded(db_engine) -> None:
    system = _create_system(db_engine)
    stale_time = datetime.now(UTC) - timedelta(days=1)
    _seed_verdict(db_engine, system=system, evaluated_at=stale_time, created_at=stale_time)
    window_start = datetime.now(UTC)
    window_end = window_start + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.verdicts.by_status == {}


def test_a_verdict_created_exactly_at_window_end_is_excluded_the_upper_bound_is_exclusive(
    db_engine,
) -> None:
    system = _create_system(db_engine)
    window_start = datetime.now(UTC)
    window_end = window_start + timedelta(minutes=1)
    _seed_verdict(db_engine, system=system, evaluated_at=window_end, created_at=window_end)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.verdicts.by_status == {}


def test_population_finding_counts_reflect_a_seeded_finding(db_engine) -> None:
    system = _create_system(db_engine)
    window_start = datetime.now(UTC)
    _seed_population_finding(
        db_engine,
        system=system,
        population_policy_id="adverse-impact-ratio",
        outcome=PopulationFindingOutcome.FLAGGED,
        evaluated_at=datetime.now(UTC),
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.population_findings.by_policy == {"adverse-impact-ratio": {"FLAGGED": 1}}


def test_verdict_review_outcome_counts_reflect_a_resolved_review(db_engine) -> None:
    system = _create_system(db_engine)
    now = datetime.now(UTC)
    verdict_id = _seed_verdict(
        db_engine,
        system=system,
        status=VerdictStatus.RECOMMEND_HOLD,
        evaluated_at=now,
        created_at=now,
    )

    window_start = datetime.now(UTC)
    _resolve_verdict_review(
        db_engine, verdict_id=verdict_id, resolution=VerdictReviewResolution.CONFIRMED
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.reviews.verdict_reviews_by_resolution == {"CONFIRMED": 1}


def test_verdict_review_outcome_counts_exclude_an_unresolved_review(db_engine) -> None:
    system = _create_system(db_engine)
    now = datetime.now(UTC)
    verdict_id = _seed_verdict(
        db_engine,
        system=system,
        status=VerdictStatus.RECOMMEND_HOLD,
        evaluated_at=now,
        created_at=now,
    )

    window_start = datetime.now(UTC)
    _create_open_verdict_review(db_engine, verdict_id=verdict_id)
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.reviews.verdict_reviews_by_resolution == {}


def test_population_finding_review_outcome_counts_reflect_a_resolved_review(db_engine) -> None:
    system = _create_system(db_engine)
    population_finding_id = _seed_population_finding(
        db_engine,
        system=system,
        outcome=PopulationFindingOutcome.FLAGGED,
        evaluated_at=datetime.now(UTC),
    )

    window_start = datetime.now(UTC)
    _resolve_population_finding_review(
        db_engine,
        population_finding_id=population_finding_id,
        resolution=PopulationFindingReviewResolution.DISMISSED,
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=system.id
    )

    assert report.reviews.population_finding_reviews_by_resolution == {"DISMISSED": 1}


def test_system_id_filter_scopes_verdicts_findings_and_verdict_reviews_to_one_system(
    db_engine,
) -> None:
    """The real join-path risk the design document names explicitly
    (`docs/milestones/M12.md` §5.1): if `--system-id` isn't respected
    identically by every one of the five queries, a report scoped to one
    system could silently include another system's review outcomes while
    correctly excluding its verdicts/findings."""
    target_system = _create_system(db_engine, name_prefix="report-target")
    other_system = _create_system(db_engine, name_prefix="report-other")
    now = datetime.now(UTC)

    window_start = datetime.now(UTC)
    target_verdict_id = _seed_verdict(
        db_engine,
        system=target_system,
        policy_id="scoped-policy",
        outcome=FindingOutcome.CLEAR,
        status=VerdictStatus.ALLOW,
        evaluated_at=now,
        created_at=now,
    )
    _seed_verdict(
        db_engine,
        system=other_system,
        policy_id="scoped-policy",
        outcome=FindingOutcome.CLEAR,
        status=VerdictStatus.ALLOW,
        evaluated_at=now,
        created_at=now,
    )
    _resolve_verdict_review(
        db_engine, verdict_id=target_verdict_id, resolution=VerdictReviewResolution.CONFIRMED
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=target_system.id
    )

    assert report.verdicts.by_status == {"ALLOW": 1}
    assert report.findings.by_policy == {"scoped-policy": {"CLEAR": 1}}
    assert report.reviews.verdict_reviews_by_resolution == {"CONFIRMED": 1}


def test_system_id_filter_scopes_population_findings_and_their_reviews_to_one_system(
    db_engine,
) -> None:
    target_system = _create_system(db_engine, name_prefix="report-pf-target")
    other_system = _create_system(db_engine, name_prefix="report-pf-other")

    window_start = datetime.now(UTC)
    target_population_finding_id = _seed_population_finding(
        db_engine,
        system=target_system,
        population_policy_id="scoped-population-policy",
        outcome=PopulationFindingOutcome.FLAGGED,
        evaluated_at=datetime.now(UTC),
    )
    _seed_population_finding(
        db_engine,
        system=other_system,
        population_policy_id="scoped-population-policy",
        outcome=PopulationFindingOutcome.FLAGGED,
        evaluated_at=datetime.now(UTC),
    )
    _resolve_population_finding_review(
        db_engine,
        population_finding_id=target_population_finding_id,
        resolution=PopulationFindingReviewResolution.CONFIRMED,
    )
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    report = get_compliance_report(
        db_engine, window_start=window_start, window_end=window_end, system_id=target_system.id
    )

    assert report.population_findings.by_policy == {"scoped-population-policy": {"FLAGGED": 1}}
    assert report.reviews.population_finding_reviews_by_resolution == {"CONFIRMED": 1}


def test_generated_at_is_set_close_to_now(db_engine) -> None:
    window_start, window_end = _far_future_window()
    before = datetime.now(UTC)

    report = get_compliance_report(db_engine, window_start=window_start, window_end=window_end)

    after = datetime.now(UTC)
    assert before <= report.generated_at <= after
