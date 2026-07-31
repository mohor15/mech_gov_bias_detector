"""`VerdictReviewRepository` — architecture §12, M9. CI-only (see
conftest.requires_postgres).

Most tests here append a real, `ALLOW` `Verdict` (via `evidence_store`, the
same helper shape `test_evidence_store_postgres.py` already uses) and then
call `VerdictReviewRepository` directly against its `verdict_id` -- `ALLOW`
deliberately, so `EvidenceStore`'s own auto-creation
(`_queue_verdict_review`) never fires and each test's own `create()` call
is the only thing creating a review row. `EvidenceStore`'s auto-creation
itself is tested separately, in `test_evidence_store_postgres.py`. The
`severity`-filter test needs a real `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD`
verdict instead, and relies on `EvidenceStore`'s own auto-creation to
produce the review rows it filters.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from gov_platform.db.models import VerdictReviewRow
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.human_review import VerdictReviewResolution, VerdictReviewStatus
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _verdict(decision_event_id: str, verdict_id: str, status: VerdictStatus) -> GovernanceVerdict:
    outcome = FindingOutcome.CLEAR if status is VerdictStatus.ALLOW else FindingOutcome.FLAGGED
    finding = Finding(
        finding_id=f"find-{verdict_id}",
        decision_event_id=decision_event_id,
        policy_id="always-allow",
        policy_version="0.1.0",
        outcome=outcome,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return GovernanceVerdict(
        verdict_id=verdict_id,
        decision_event_id=decision_event_id,
        status=status,
        findings=[finding],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _unique_event_id() -> str:
    return f"evt-{uuid4()}"


def _new_verdict_id(evidence_store, make_decision_event) -> str:
    """An `ALLOW` verdict -- `EvidenceStore`'s own auto-creation never
    fires for it, so it's a clean FK target for testing
    `VerdictReviewRepository` in isolation."""
    event = make_decision_event(event_id=_unique_event_id())
    verdict_id = str(uuid4())
    evidence_store.append(event, _verdict(event.event_id, verdict_id, VerdictStatus.ALLOW))
    return verdict_id


def test_create_returns_an_open_review(evidence_store, make_decision_event, db_engine) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        review = repository.create(session, verdict_id)
        session.commit()

    assert review is not None
    assert review.verdict_id == verdict_id
    assert review.status is VerdictReviewStatus.OPEN
    assert review.reviewer is None


def test_create_is_idempotent_while_a_review_is_still_active(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        first = repository.create(session, verdict_id)
        session.commit()
    with Session(db_engine) as session:
        second = repository.create(session, verdict_id)
        session.commit()

    assert first is not None
    assert second is None  # an active review already exists -- silent no-op, never an error


def test_get_returns_none_for_an_unknown_id(db_engine) -> None:
    with Session(db_engine) as session:
        assert VerdictReviewRepository().get(session, f"no-such-review-{uuid4()}") is None


def test_claim_transitions_open_to_in_review(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        claimed = repository.claim(session, created.id, "jane")
        session.commit()

    assert claimed.status is VerdictReviewStatus.IN_REVIEW
    assert claimed.reviewer == "jane"
    assert claimed.claimed_at is not None


def test_claim_raises_for_an_already_claimed_review(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.claim(session, created.id, "someone-else")


def test_claim_raises_for_an_already_resolved_review(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.DISMISSED,
            notes="false positive",
        )
        session.commit()

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.claim(session, created.id, "someone-else")


def test_the_claim_race_directly(evidence_store, make_decision_event, db_engine) -> None:
    """Exactly one of several concurrent `claim()` calls against the same
    `OPEN` row succeeds; the rest observe zero-rows-affected and raise --
    never both silently "succeeding" with the last write winning
    (docs/milestones/M9.md §4.4/§7)."""
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    results: list[str] = []
    lock = threading.Lock()

    def _try_claim(reviewer: str) -> None:
        try:
            with Session(db_engine) as session:
                repository.claim(session, created.id, reviewer)
                session.commit()
            outcome = "success"
        except ValueError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_try_claim, args=(f"reviewer-{i}",)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("success") == 1
    assert results.count("conflict") == 9


def test_release_returns_an_in_review_item_to_open(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session:
        released = repository.release(session, created.id)
        session.commit()

    assert released.status is VerdictReviewStatus.OPEN
    assert released.reviewer is None
    assert released.claimed_at is None


def test_release_allows_a_different_reviewer_to_claim_next(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()
    with Session(db_engine) as session:
        repository.release(session, created.id)
        session.commit()
    with Session(db_engine) as session:
        claimed_again = repository.claim(session, created.id, "someone-else")
        session.commit()

    assert claimed_again.reviewer == "someone-else"


def test_release_raises_for_an_item_that_is_not_in_review(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.release(session, created.id)  # still OPEN, never claimed


def test_resolve_transitions_in_review_to_resolved(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session:
        resolved = repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="a real, actionable disparity",
        )
        session.commit()

    assert resolved.status is VerdictReviewStatus.RESOLVED
    assert resolved.resolution is VerdictReviewResolution.CONFIRMED
    assert resolved.resolution_notes == "a real, actionable disparity"
    assert resolved.resolved_at is not None


def test_resolve_raises_for_a_review_that_was_never_claimed(
    evidence_store, make_decision_event, db_engine
) -> None:
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="test",
        )


def test_resolve_raises_when_the_reviewer_does_not_match_who_claimed_it(
    evidence_store, make_decision_event, db_engine
) -> None:
    """The identity-continuity check (docs/milestones/M9.md §3.3/§7): even
    though the row is genuinely IN_REVIEW, a different `reviewer` string
    cannot resolve it."""
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.resolve(
            session,
            created.id,
            reviewer="someone-else",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="test",
        )


def test_a_resolved_review_can_be_reopened_via_a_new_row(
    evidence_store, make_decision_event, db_engine
) -> None:
    """docs/milestones/M9.md §3.2/§3.3: RESOLVED is terminal for one row,
    not for the verdict it references -- a partial unique index, not a
    plain UNIQUE, so a second, independent review can open once the first
    is resolved, without ever mutating the first."""
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        first = repository.create(session, verdict_id)
        session.commit()
    assert first is not None

    with Session(db_engine) as session:
        repository.claim(session, first.id, "jane")
        repository.resolve(
            session,
            first.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.DISMISSED,
            notes="false positive",
        )
        session.commit()

    with Session(db_engine) as session:
        second = repository.create(session, verdict_id)
        session.commit()

    assert second is not None
    assert second.id != first.id
    assert second.status is VerdictReviewStatus.OPEN

    with Session(db_engine) as session:
        first_reloaded = repository.get(session, first.id)
    assert first_reloaded is not None
    assert first_reloaded.status is VerdictReviewStatus.RESOLVED
    assert first_reloaded.resolution is VerdictReviewResolution.DISMISSED  # untouched


def test_create_is_a_no_op_while_a_reopened_review_is_still_active(
    evidence_store, make_decision_event, db_engine
) -> None:
    """The partial unique index still blocks a *second* concurrently-active
    review for the same verdict, even after one reopen -- it only ever
    permits at most one active row at a time."""
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    with Session(db_engine) as session:
        first = repository.create(session, verdict_id)
        session.commit()
    assert first is not None

    with Session(db_engine) as session:
        repository.claim(session, first.id, "jane")
        repository.resolve(
            session,
            first.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.DISMISSED,
            notes="false positive",
        )
        session.commit()

    with Session(db_engine) as session:
        second = repository.create(session, verdict_id)
        session.commit()
    assert second is not None

    with Session(db_engine) as session:
        third = repository.create(session, verdict_id)
        session.commit()

    assert third is None  # `second` is still active -- silent no-op


def test_list_all_defaults_to_oldest_open_first(
    evidence_store, make_decision_event, db_engine
) -> None:
    repository = VerdictReviewRepository()
    verdict_id_a = _new_verdict_id(evidence_store, make_decision_event)
    verdict_id_b = _new_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        review_a = repository.create(session, verdict_id_a)
        review_b = repository.create(session, verdict_id_b)
        session.commit()
    assert review_a is not None
    assert review_b is not None

    with Session(db_engine) as session:
        reviews = repository.list_all(session)

    ids_in_order = [r.id for r in reviews]
    assert ids_in_order.index(review_a.id) < ids_in_order.index(review_b.id)


def test_list_all_filters_by_status(evidence_store, make_decision_event, db_engine) -> None:
    repository = VerdictReviewRepository()
    verdict_id_open = _new_verdict_id(evidence_store, make_decision_event)
    verdict_id_resolved = _new_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        open_review = repository.create(session, verdict_id_open)
        resolved_review = repository.create(session, verdict_id_resolved)
        session.commit()
    assert open_review is not None
    assert resolved_review is not None

    with Session(db_engine) as session:
        repository.claim(session, resolved_review.id, "jane")
        repository.resolve(
            session,
            resolved_review.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="test",
        )
        session.commit()

    with Session(db_engine) as session:
        open_only = repository.list_all(session, status=VerdictReviewStatus.OPEN)

    open_only_ids = {r.id for r in open_only}
    assert open_review.id in open_only_ids
    assert resolved_review.id not in open_only_ids


def test_list_all_filters_by_severity(evidence_store, make_decision_event, db_engine) -> None:
    """`severity` joins to the referenced Verdict's own `status`
    (docs/milestones/M9.md §3.7): a RECOMMEND_HOLD review is filtered
    separately from an ESCALATE_FOR_REVIEW one, even though both are
    `VerdictReviewStatus.OPEN`. Relies on `EvidenceStore`'s own
    auto-creation (`_queue_verdict_review`) to produce both review rows."""
    escalate_event = make_decision_event(event_id=_unique_event_id())
    hold_event = make_decision_event(event_id=_unique_event_id())
    escalate_verdict_id = str(uuid4())
    hold_verdict_id = str(uuid4())

    evidence_store.append(
        escalate_event,
        _verdict(escalate_event.event_id, escalate_verdict_id, VerdictStatus.ESCALATE_FOR_REVIEW),
    )
    evidence_store.append(
        hold_event,
        _verdict(hold_event.event_id, hold_verdict_id, VerdictStatus.RECOMMEND_HOLD),
    )

    with Session(db_engine) as session:
        repository = VerdictReviewRepository()
        hold_only = repository.list_all(session, severity=VerdictStatus.RECOMMEND_HOLD)
        verdicts_by_id = VerdictRepository().get_many(session, [r.verdict_id for r in hold_only])

    assert all(
        verdicts_by_id[r.verdict_id].status is VerdictStatus.RECOMMEND_HOLD for r in hold_only
    )
    hold_only_verdict_ids = {r.verdict_id for r in hold_only}
    assert hold_verdict_id in hold_only_verdict_ids
    assert escalate_verdict_id not in hold_only_verdict_ids


def test_list_all_respects_limit(evidence_store, make_decision_event, db_engine) -> None:
    repository = VerdictReviewRepository()
    with Session(db_engine) as session:
        for _ in range(3):
            verdict_id = _new_verdict_id(evidence_store, make_decision_event)
            repository.create(session, verdict_id)
        session.commit()

        limited = repository.list_all(session, limit=2)

    assert len(limited) == 2


def test_list_all_respects_offset(evidence_store, make_decision_event, db_engine) -> None:
    repository = VerdictReviewRepository()
    verdict_id_a = _new_verdict_id(evidence_store, make_decision_event)
    verdict_id_b = _new_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        review_a = repository.create(session, verdict_id_a)
        review_b = repository.create(session, verdict_id_b)
        session.commit()
    assert review_a is not None
    assert review_b is not None

    with Session(db_engine) as session:
        first_page = repository.list_all(session, limit=1)
        second_page = repository.list_all(session, limit=1, offset=1)

    assert first_page[0].id != second_page[0].id


def test_offset_without_limit_returns_everything_after_the_skipped_row(
    evidence_store, make_decision_event, db_engine
) -> None:
    """M15 §5.1: `limit`/`offset` are independent -- `offset` alone is
    valid, ordinary SQL, not an error."""
    repository = VerdictReviewRepository()
    verdict_id_a = _new_verdict_id(evidence_store, make_decision_event)
    verdict_id_b = _new_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        review_a = repository.create(session, verdict_id_a)
        review_b = repository.create(session, verdict_id_b)
        session.commit()
    assert review_a is not None
    assert review_b is not None

    with Session(db_engine) as session:
        everything = repository.list_all(session)
        skipped_first = repository.list_all(session, offset=1)

    assert len(skipped_first) == len(everything) - 1


def test_pagination_is_stable_when_two_reviews_share_created_at(
    evidence_store, make_decision_event, db_engine
) -> None:
    """M15 §5.2, mirroring `docs/milestones/M4.md` §13.7's own already-
    shipped fix: `created_at` alone is not a unique sort key -- two reviews
    queued from the same batch write can share it (`create()` itself has
    no caller-settable timestamp, so the tie is forced directly at the row
    level here, the only way to construct this scenario deterministically).
    Paging through with `limit=1` must visit every row exactly once."""
    repository = VerdictReviewRepository()
    verdict_ids = [_new_verdict_id(evidence_store, make_decision_event) for _ in range(4)]

    with Session(db_engine) as session:
        reviews = [repository.create(session, vid) for vid in verdict_ids]
        session.commit()
    created_ids = {r.id for r in reviews if r is not None}
    assert len(created_ids) == 4

    shared_created_at = datetime(2026, 6, 1, tzinfo=UTC)
    with Session(db_engine) as session:
        session.execute(
            update(VerdictReviewRow)
            .where(VerdictReviewRow.id.in_(created_ids))
            .values(created_at=shared_created_at)
        )
        session.commit()

    # `verdict_reviews` is shared and never truncated across the whole test
    # session (the same discipline `test_admin_population_finding_reviews_api.py`
    # documents for `population_findings`), so paging until an empty page
    # would walk every row any other test in this run has ever created.
    # `shared_created_at` sorts before `datetime.now(UTC)`-stamped rows from
    # every other test, so the four rows of interest are always among the
    # very first pages -- stop as soon as all four are accounted for.
    with Session(db_engine) as session:
        seen: list[str] = []
        offset = 0
        while len(set(seen) & created_ids) < len(created_ids):
            page = repository.list_all(session, limit=1, offset=offset)
            if not page:
                break
            seen.append(page[0].id)
            offset += 1

    seen_of_interest = [rid for rid in seen if rid in created_ids]
    assert len(seen_of_interest) == len(created_ids)
    assert len(set(seen_of_interest)) == len(created_ids)  # no duplicate, no skip


def test_the_backfill_and_live_traffic_race_never_raises_for_either_writer(
    evidence_store, make_decision_event, db_engine
) -> None:
    """docs/milestones/M9.md §3.4/§4.8: both the live path and the
    reconciliation tool use the identical idempotent-upsert `create()` --
    two concurrent callers racing to create a review for the same verdict
    never raise; exactly one review row results."""
    verdict_id = _new_verdict_id(evidence_store, make_decision_event)
    repository = VerdictReviewRepository()

    results: list[object] = []
    lock = threading.Lock()

    def _try_create() -> None:
        with Session(db_engine) as session:
            outcome = repository.create(session, verdict_id)
            session.commit()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_try_create) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    successes = [r for r in results if r is not None]
    assert len(successes) == 1

    with Session(db_engine) as session:
        all_reviews = [r for r in repository.list_all(session) if r.verdict_id == verdict_id]
    assert len(all_reviews) == 1
