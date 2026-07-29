"""`human_review/backfill_reviews.py` — architecture §12, M9. CI-only (see
conftest.requires_postgres).

Seeds pre-existing `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` verdicts and
`FLAGGED` findings *without* letting the live write path's own
auto-creation run (constructing `EvidenceStore`/persisting the finding
directly via repositories, bypassing `_queue_verdict_review`/
`_queue_population_finding_review` entirely is not straightforward for
`EvidenceStore.append`, since auto-creation is unconditional inside it --
instead, each test manually deletes the auto-created review row first, to
simulate "a real deployment reaching M9 with pre-existing, un-reviewed
escalations" honestly) -- then runs `reconcile_verdict_reviews`/
`reconcile_population_finding_reviews` and confirms the gap is closed.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.models import PopulationFindingReviewRow, VerdictReviewRow
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.human_review.backfill_reviews import (
    reconcile_population_finding_reviews,
    reconcile_verdict_reviews,
)
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _verdict(decision_event_id: str, verdict_id: str) -> GovernanceVerdict:
    finding = Finding(
        finding_id=f"find-{verdict_id}",
        decision_event_id=decision_event_id,
        policy_id="high-debt-ratio-gate",
        policy_version="0.1.0",
        outcome=FindingOutcome.FLAGGED,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return GovernanceVerdict(
        verdict_id=verdict_id,
        decision_event_id=decision_event_id,
        status=VerdictStatus.ESCALATE_FOR_REVIEW,
        findings=[finding],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _seed_pre_m9_verdict(db_engine, make_decision_event) -> str:
    """A qualifying Verdict with its auto-created review row deleted, to
    simulate a real pre-M9 deployment's un-reviewed backlog."""
    evidence_store = EvidenceStore(db_engine)
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    evidence_store.append(event, _verdict(event.event_id, verdict_id))

    with Session(db_engine) as session:
        session.execute(delete(VerdictReviewRow).where(VerdictReviewRow.verdict_id == verdict_id))
        session.commit()

    return verdict_id


def _seed_pre_m9_population_finding(db_engine) -> str:
    with Session(db_engine) as session:
        system_id = SystemRepository().create(session, name=f"backfill-system-{uuid4()}").id
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system_id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.FLAGGED,
            metric_values={"race:Black": 0.75},
            classification_snapshot={"race": "DIRECT"},
            rationale="test rationale",
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()
    return finding.population_finding_id


def test_reconcile_verdict_reviews_creates_a_review_for_a_pre_existing_gap(
    postgres_url, db_engine, make_decision_event
) -> None:
    verdict_id = _seed_pre_m9_verdict(db_engine, make_decision_event)

    created, errored = reconcile_verdict_reviews(postgres_url)

    assert errored == 0
    assert created >= 1
    with Session(db_engine) as session:
        row = session.execute(
            select(VerdictReviewRow).where(VerdictReviewRow.verdict_id == verdict_id)
        ).scalar_one_or_none()
    assert row is not None
    assert row.status == "OPEN"


def test_reconcile_verdict_reviews_run_twice_is_a_genuine_no_op(
    postgres_url, db_engine, make_decision_event
) -> None:
    _seed_pre_m9_verdict(db_engine, make_decision_event)

    reconcile_verdict_reviews(postgres_url)
    with Session(db_engine) as session:
        count_after_first_run = session.execute(select(VerdictReviewRow.id)).scalars().all()

    reconcile_verdict_reviews(postgres_url)
    with Session(db_engine) as session:
        count_after_second_run = session.execute(select(VerdictReviewRow.id)).scalars().all()

    assert len(count_after_second_run) == len(count_after_first_run)


def test_reconcile_population_finding_reviews_creates_a_review_for_a_pre_existing_gap(
    postgres_url, db_engine
) -> None:
    finding_id = _seed_pre_m9_population_finding(db_engine)

    created, errored = reconcile_population_finding_reviews(postgres_url)

    assert errored == 0
    assert created >= 1
    with Session(db_engine) as session:
        row = session.execute(
            select(PopulationFindingReviewRow).where(
                PopulationFindingReviewRow.population_finding_id == finding_id
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.status == "OPEN"


def test_reconcile_does_not_queue_a_clear_population_finding(postgres_url, db_engine) -> None:
    with Session(db_engine) as session:
        system_id = SystemRepository().create(session, name=f"backfill-clear-{uuid4()}").id
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system_id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.CLEAR,
            metric_values={},
            classification_snapshot={},
            rationale="test rationale",
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()

    reconcile_population_finding_reviews(postgres_url)

    with Session(db_engine) as session:
        row = session.execute(
            select(PopulationFindingReviewRow).where(
                PopulationFindingReviewRow.population_finding_id == finding.population_finding_id
            )
        ).scalar_one_or_none()
    assert row is None


def test_reconciliation_racing_live_traffic_never_raises_and_creates_exactly_one_row(
    postgres_url, db_engine, make_decision_event
) -> None:
    """docs/milestones/M9.md §3.4/§4.8: the tool's own idempotent upsert
    means it can safely race a concurrent live-path insert for the same
    verdict -- neither writer raises, and exactly one review row results."""
    verdict_id = _seed_pre_m9_verdict(db_engine, make_decision_event)
    live_repository = VerdictReviewRepository()

    results: list[str] = []
    lock = threading.Lock()

    def _run_reconciliation() -> None:
        try:
            reconcile_verdict_reviews(postgres_url)
            outcome = "ok"
        except Exception:
            outcome = "error"
        with lock:
            results.append(outcome)

    def _run_live_insert() -> None:
        try:
            with Session(db_engine) as session:
                live_repository.create(session, verdict_id)
                session.commit()
            outcome = "ok"
        except Exception:
            outcome = "error"
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=_run_reconciliation),
        threading.Thread(target=_run_live_insert),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("error") == 0

    with Session(db_engine) as session:
        rows = (
            session.execute(
                select(VerdictReviewRow).where(VerdictReviewRow.verdict_id == verdict_id)
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
