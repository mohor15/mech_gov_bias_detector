"""Reconciliation tool for Human Review Workflow — architecture §12, M9.

Creates an `OPEN` review for every reviewable `Verdict`/`PopulationFinding`
that doesn't already have an *active* one. Two jobs, one mechanism:

1. **Historical backfill.** Same-transaction creation never existed for
   this milestone (see `docs/milestones/M9.md` §3.4) — every
   `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` `Verdict` and `FLAGGED`
   `PopulationFinding` already sitting in a real deployment's database from
   M5 through M8 needs a review row created for it once, or it is
   permanently, silently excluded from this workflow. Run this once,
   immediately after M9's migrations and code ship.
2. **Live-path safety net.** `audit/evidence_store.py`'s
   `_queue_verdict_review` and `population_engine/run_policies.py`'s
   `_queue_population_finding_review` each create a review row in their own
   separate transaction, deliberately decoupled from the write they depend
   on (§3.4) — a failure there is logged and swallowed, never propagated,
   so a real (if rare) qualifying record can end up with no review row.
   This tool closes that gap too.

Reframed, on this milestone's own hostile-review pass, from a one-time
backfill script into a standing tool: **safe, and recommended, to re-run
periodically** (an ops cron entry, or manually after any incident), not
just once at rollout — closer in spirit to `audit/verify_chain.py` (a
permanent, reusable tool this platform re-runs whenever it wants
assurance) than to `infra/ci/setup_test_role.py` (genuinely one-shot,
CI-only tooling). Mirrors `plugins/seed_registry.py`'s own invocation
shape: a separate, explicitly-invoked step, never something `create_app()`
or `db.migrate` does implicitly, and not a daemon or in-process scheduler
(the identical "no new background-job mechanism" discipline
`docs/milestones/M6.md` §13.4 already established for
`population_engine/run_policies.py`).

Idempotent by construction, not just by convention: every insert goes
through `VerdictReviewRepository.create`/`PopulationFindingReviewRepository.create`,
the same `ON CONFLICT ... DO NOTHING` upsert the live write path uses — so
this tool can safely run concurrently with live ingestion, with itself
(two operators triggering it by accident), or with the live path's own
decoupled insert, and no writer ever raises for losing that race
(`docs/milestones/M9.md` §3.4/§4.8). Scoped to the identical
`_REVIEWABLE_VERDICT_STATUSES` constant the live write path imports — one
definition, two consumers, never an independently-maintained copy of
"which statuses count" that could silently drift.

Each candidate record is reconciled in its own short-lived `Session`, the
same per-record isolation `population_engine/run_policies.py` already uses
per binding: one record's failure (a transient DB error, a genuine bug) is
logged and counted, never allowed to abort reconciling the rest. Exits
non-zero if any record actually errored, so an ops wrapper can alert on
real failures — a conflict (an active review already exists) is not an
error, the same "clean skip, not a failure" distinction
`run_policies.py`'s own duplicate-window handling already draws.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import PopulationFindingRow, VerdictRow
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.db.session import create_db_engine
from gov_platform.schemas.human_review import _REVIEWABLE_VERDICT_STATUSES
from gov_platform.schemas.population_finding import PopulationFindingOutcome

logger = logging.getLogger(__name__)


def reconcile_verdict_reviews(database_url: str) -> tuple[int, int]:
    """Returns `(created, errored)` counts. Never raises for an individual
    record's failure — see this module's docstring."""
    engine = create_db_engine(database_url)
    repository = VerdictReviewRepository()

    with Session(engine) as session:
        verdict_ids = (
            session.execute(
                select(VerdictRow.id).where(
                    VerdictRow.status.in_([s.value for s in _REVIEWABLE_VERDICT_STATUSES])
                )
            )
            .scalars()
            .all()
        )

    created = 0
    errored = 0
    for verdict_id in verdict_ids:
        try:
            with Session(engine) as session:
                if repository.create(session, verdict_id) is not None:
                    created += 1
                session.commit()
        except Exception:
            errored += 1
            logger.exception(
                "verdict_review_reconciliation_failed",
                extra={"extra_fields": {"verdict_id": verdict_id}},
            )

    return created, errored


def reconcile_population_finding_reviews(database_url: str) -> tuple[int, int]:
    """Returns `(created, errored)` counts. Never raises for an individual
    record's failure — see this module's docstring."""
    engine = create_db_engine(database_url)
    repository = PopulationFindingReviewRepository()

    with Session(engine) as session:
        finding_ids = (
            session.execute(
                select(PopulationFindingRow.id).where(
                    PopulationFindingRow.outcome == PopulationFindingOutcome.FLAGGED.value
                )
            )
            .scalars()
            .all()
        )

    created = 0
    errored = 0
    for finding_id in finding_ids:
        try:
            with Session(engine) as session:
                if repository.create(session, finding_id) is not None:
                    created += 1
                session.commit()
        except Exception:
            errored += 1
            logger.exception(
                "population_finding_review_reconciliation_failed",
                extra={"extra_fields": {"population_finding_id": finding_id}},
            )

    return created, errored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile Human Review Workflow queues: create an OPEN review for every "
            "reviewable Verdict/PopulationFinding with no active review yet. Idempotent -- "
            "safe to run once at rollout and safe to re-run periodically thereafter, "
            "including concurrently with live traffic or with itself."
        )
    )
    parser.add_argument("--database-url", required=True, help="The app's own runtime connection")
    args = parser.parse_args(argv)

    verdict_reviews_created, verdict_reviews_errored = reconcile_verdict_reviews(args.database_url)
    print(f"verdict_reviews created: {verdict_reviews_created}")

    population_finding_reviews_created, population_finding_reviews_errored = (
        reconcile_population_finding_reviews(args.database_url)
    )
    print(f"population_finding_reviews created: {population_finding_reviews_created}")

    total_errored = verdict_reviews_errored + population_finding_reviews_errored
    if total_errored:
        print(f"ERROR: {total_errored} record(s) failed to reconcile -- see logs")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
