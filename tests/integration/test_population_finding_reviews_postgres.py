"""`PopulationFindingReviewRepository` — architecture §12, M9. CI-only (see
conftest.requires_postgres).

Mirrors `test_verdict_reviews_postgres.py` exactly, for `PopulationFinding`
instead of `Verdict`. Most tests seed a real, `CLEAR` `PopulationFinding`
directly via `PopulationFindingRepository` (the same pattern
`test_admin_population_findings_api.py` already uses) and then call
`PopulationFindingReviewRepository` directly against its
`population_finding_id` — `CLEAR` deliberately, so
`population_engine/run_policies.py`'s own auto-creation never applies here
(this file never runs that batch job at all).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.human_review import (
    PopulationFindingReviewResolution,
    PopulationFindingReviewStatus,
)
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _new_population_finding_id(db_engine, *, outcome: PopulationFindingOutcome) -> str:
    with Session(db_engine) as session:
        system_id = SystemRepository().create(session, name=f"review-test-system-{uuid4()}").id
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system_id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=outcome,
            metric_values={"race:Black": 0.75},
            classification_snapshot={"race": "DIRECT"},
            rationale="test rationale",
            # A unique evaluated_at -- see
            # test_admin_population_finding_reviews_api.py's identical
            # comment for why a shared, fixed timestamp is unsafe here.
            evaluated_at=datetime.now(UTC),
        )
        PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()
    return finding.population_finding_id


def _new_finding_id(db_engine) -> str:
    return _new_population_finding_id(db_engine, outcome=PopulationFindingOutcome.CLEAR)


def test_create_returns_an_open_review(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        review = repository.create(session, finding_id)
        session.commit()

    assert review is not None
    assert review.population_finding_id == finding_id
    assert review.status is PopulationFindingReviewStatus.OPEN
    assert review.reviewer is None


def test_create_is_idempotent_while_a_review_is_still_active(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        first = repository.create(session, finding_id)
        session.commit()
    with Session(db_engine) as session:
        second = repository.create(session, finding_id)
        session.commit()

    assert first is not None
    assert second is None


def test_get_returns_none_for_an_unknown_id(db_engine) -> None:
    with Session(db_engine) as session:
        assert PopulationFindingReviewRepository().get(session, f"no-such-review-{uuid4()}") is None


def test_claim_transitions_open_to_in_review(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        claimed = repository.claim(session, created.id, "jane")
        session.commit()

    assert claimed.status is PopulationFindingReviewStatus.IN_REVIEW
    assert claimed.reviewer == "jane"
    assert claimed.claimed_at is not None


def test_claim_raises_for_an_already_claimed_review(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.claim(session, created.id, "someone-else")


def test_the_claim_race_directly(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
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


def test_release_returns_an_in_review_item_to_open(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        session.commit()

    with Session(db_engine) as session:
        released = repository.release(session, created.id)
        session.commit()

    assert released.status is PopulationFindingReviewStatus.OPEN
    assert released.reviewer is None


def test_release_raises_for_an_item_that_is_not_in_review(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.release(session, created.id)


def test_resolve_transitions_in_review_to_resolved(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
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
            resolution=PopulationFindingReviewResolution.CONFIRMED,
            notes="a real, actionable disparity",
        )
        session.commit()

    assert resolved.status is PopulationFindingReviewStatus.RESOLVED
    assert resolved.resolution is PopulationFindingReviewResolution.CONFIRMED
    assert resolved.resolved_at is not None


def test_resolve_raises_when_the_reviewer_does_not_match_who_claimed_it(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        created = repository.create(session, finding_id)
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
            resolution=PopulationFindingReviewResolution.CONFIRMED,
            notes="test",
        )


def test_a_resolved_review_can_be_reopened_via_a_new_row(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    with Session(db_engine) as session:
        first = repository.create(session, finding_id)
        session.commit()
    assert first is not None

    with Session(db_engine) as session:
        repository.claim(session, first.id, "jane")
        repository.resolve(
            session,
            first.id,
            reviewer="jane",
            resolution=PopulationFindingReviewResolution.DISMISSED,
            notes="false positive",
        )
        session.commit()

    with Session(db_engine) as session:
        second = repository.create(session, finding_id)
        session.commit()

    assert second is not None
    assert second.id != first.id
    assert second.status is PopulationFindingReviewStatus.OPEN

    with Session(db_engine) as session:
        first_reloaded = repository.get(session, first.id)
    assert first_reloaded is not None
    assert first_reloaded.status is PopulationFindingReviewStatus.RESOLVED


def test_list_all_defaults_to_oldest_open_first(db_engine) -> None:
    repository = PopulationFindingReviewRepository()
    finding_id_a = _new_finding_id(db_engine)
    finding_id_b = _new_finding_id(db_engine)

    with Session(db_engine) as session:
        review_a = repository.create(session, finding_id_a)
        review_b = repository.create(session, finding_id_b)
        session.commit()
    assert review_a is not None
    assert review_b is not None

    with Session(db_engine) as session:
        reviews = repository.list_all(session)

    ids_in_order = [r.id for r in reviews]
    assert ids_in_order.index(review_a.id) < ids_in_order.index(review_b.id)


def test_list_all_filters_by_status(db_engine) -> None:
    repository = PopulationFindingReviewRepository()
    finding_id_open = _new_finding_id(db_engine)
    finding_id_resolved = _new_finding_id(db_engine)

    with Session(db_engine) as session:
        open_review = repository.create(session, finding_id_open)
        resolved_review = repository.create(session, finding_id_resolved)
        session.commit()
    assert open_review is not None
    assert resolved_review is not None

    with Session(db_engine) as session:
        repository.claim(session, resolved_review.id, "jane")
        repository.resolve(
            session,
            resolved_review.id,
            reviewer="jane",
            resolution=PopulationFindingReviewResolution.CONFIRMED,
            notes="test",
        )
        session.commit()

    with Session(db_engine) as session:
        open_only = repository.list_all(session, status=PopulationFindingReviewStatus.OPEN)

    open_only_ids = {r.id for r in open_only}
    assert open_review.id in open_only_ids
    assert resolved_review.id not in open_only_ids


def test_the_backfill_and_live_traffic_race_never_raises_for_either_writer(db_engine) -> None:
    finding_id = _new_finding_id(db_engine)
    repository = PopulationFindingReviewRepository()

    results: list[object] = []
    lock = threading.Lock()

    def _try_create() -> None:
        with Session(db_engine) as session:
            outcome = repository.create(session, finding_id)
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
        all_reviews = [
            r for r in repository.list_all(session) if r.population_finding_id == finding_id
        ]
    assert len(all_reviews) == 1
