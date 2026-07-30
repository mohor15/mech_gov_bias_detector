"""CLI: delete rows older than each table's configured retention window —
architecture §13, M11.

Retention tiers apply to exactly two tables, `shadow_findings` and
`protected_attribute_resolutions` — the only tables in this schema that
are simultaneously (a) not part of the hash chain or any other
tamper-evident guarantee, and (b) not locked against deletion at the
database-privilege level (see migrations `0025`/`0026`). See
`docs/milestones/M11.md` §4.2/§5.2 for the full design rationale,
including why `evidence_chain`/`population_findings` and the six
operational tables migration `0025` locks down are deliberately out of
scope, and §4.4 for a disclosed caveat on `protected_attribute_resolutions`
specifically (a purged row's original classification is reproducible by
re-running the resolver only if `protected_attribute_rules` hasn't
changed since — the raw attribute values themselves are never at risk,
since retention never touches `decision_events`/`evidence_chain.payload`).

Mirrors `population_engine/run_policies.py`'s and
`human_review/backfill_reviews.py`'s existing CLI shape: no daemon, no
in-process scheduler — an explicitly-invoked, idempotent tool an operator
runs on their own cron/`CronJob` cadence (real scheduling remains
deployment-topology scope, architecture §17/M13, unchanged). Runs under a
separate, more-privileged database connection than the app's own runtime
role (`--database-url`, never `Settings.DATABASE_URL`) — mirrors
`db/migrate.py`'s own already-established precedent for exactly this kind
of ops-time, elevated-privilege operation (`docs/milestones/M11.md`
§5.2/§12.11): the app's own `gov_platform_app` role has no `DELETE`
privilege on either table as of migration `0026`.

Retention windows themselves (`RETENTION_DAYS_SHADOW_FINDINGS`/
`RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS`) are read from the
process-wide `Settings` model, not a CLI flag — the same
`GOV_PLATFORM_`-prefixed environment-variable convention every other
governance-sensitive constant in this platform already uses. Neither has a
numeric default: a table with no configured window is skipped entirely,
logged as such, never silently defaulted to some assumed period (see
`config/settings.py`'s own docstring for why no external standard exists
to source a defensible number from, unlike the EEOC ratio or the CFPB
threshold).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import Session

from gov_platform.config.settings import get_settings
from gov_platform.db.models import ProtectedAttributeResolutionRow, ShadowFindingRow
from gov_platform.db.session import create_db_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PurgeResult:
    """One table's outcome for one invocation. `skipped=True` means no
    retention window is configured for this table — a clean, expected
    no-op, not a failure."""

    table_name: str
    retention_days: int | None
    cutoff: datetime | None
    deleted_count: int
    skipped: bool


def compute_cutoff(retention_days: int, *, now: datetime) -> datetime:
    """Rows strictly older than this cutoff are eligible for deletion."""
    return now - timedelta(days=retention_days)


def purge_shadow_findings(
    session: Session, retention_days: int | None, *, now: datetime
) -> PurgeResult:
    """Deletes every `shadow_findings` row with `evaluated_at` strictly
    older than `retention_days` before `now`. `retention_days=None` is a
    no-op, logged as such — not a fallback to any assumed period."""
    table_name = "shadow_findings"
    if retention_days is None:
        logger.info("retention_skipped_unconfigured", extra={"extra_fields": {"table": table_name}})
        return PurgeResult(
            table_name=table_name, retention_days=None, cutoff=None, deleted_count=0, skipped=True
        )

    cutoff = compute_cutoff(retention_days, now=now)
    result = session.execute(delete(ShadowFindingRow).where(ShadowFindingRow.evaluated_at < cutoff))
    assert isinstance(result, CursorResult)  # a Core DELETE always returns one
    deleted_count = result.rowcount
    logger.info(
        "retention_purge_completed",
        extra={
            "extra_fields": {
                "table": table_name,
                "cutoff": cutoff.isoformat(),
                "deleted_count": deleted_count,
            }
        },
    )
    return PurgeResult(
        table_name=table_name,
        retention_days=retention_days,
        cutoff=cutoff,
        deleted_count=deleted_count,
        skipped=False,
    )


def purge_protected_attribute_resolutions(
    session: Session, retention_days: int | None, *, now: datetime
) -> PurgeResult:
    """Deletes every `protected_attribute_resolutions` row with
    `resolved_at` strictly older than `retention_days` before `now`.
    `retention_days=None` is a no-op, logged as such."""
    table_name = "protected_attribute_resolutions"
    if retention_days is None:
        logger.info("retention_skipped_unconfigured", extra={"extra_fields": {"table": table_name}})
        return PurgeResult(
            table_name=table_name, retention_days=None, cutoff=None, deleted_count=0, skipped=True
        )

    cutoff = compute_cutoff(retention_days, now=now)
    result = session.execute(
        delete(ProtectedAttributeResolutionRow).where(
            ProtectedAttributeResolutionRow.resolved_at < cutoff
        )
    )
    assert isinstance(result, CursorResult)  # a Core DELETE always returns one
    deleted_count = result.rowcount
    logger.info(
        "retention_purge_completed",
        extra={
            "extra_fields": {
                "table": table_name,
                "cutoff": cutoff.isoformat(),
                "deleted_count": deleted_count,
            }
        },
    )
    return PurgeResult(
        table_name=table_name,
        retention_days=retention_days,
        cutoff=cutoff,
        deleted_count=deleted_count,
        skipped=False,
    )


def run_purge(
    engine: Engine,
    *,
    retention_days_shadow_findings: int | None,
    retention_days_protected_attribute_resolutions: int | None,
    now: datetime | None = None,
) -> list[PurgeResult]:
    """Runs both tables' purges for one invocation, each in its own
    transaction — one table's outcome (skip, purge, or a raised exception)
    never depends on or blocks the other's. Safe to re-run at any cadence:
    a run against an already-purged table (or one with nothing past its
    cutoff yet) simply deletes zero rows, the identical idempotency bar
    `human_review/backfill_reviews.py` already holds itself to. No new
    persisted "last purged at" state is needed — the operation is
    naturally idempotent from its own cutoff-timestamp logic alone, so
    nothing extra needs tracking."""
    resolved_now = now or datetime.now(UTC)
    results: list[PurgeResult] = []

    with Session(engine) as session:
        results.append(
            purge_shadow_findings(session, retention_days_shadow_findings, now=resolved_now)
        )
        session.commit()

    with Session(engine) as session:
        results.append(
            purge_protected_attribute_resolutions(
                session, retention_days_protected_attribute_resolutions, now=resolved_now
            )
        )
        session.commit()

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete rows older than each table's configured retention window from "
            "shadow_findings and protected_attribute_resolutions. Idempotent -- safe to "
            "run once or on any recurring schedule. A table with no configured "
            "RETENTION_DAYS_* setting is skipped entirely, logged as such, never "
            "silently defaulted to an assumed period."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="A connection string with DELETE privilege on shadow_findings and "
        "protected_attribute_resolutions -- the app's own runtime role does not have "
        "it as of migration 0026 (see docs/milestones/M11.md §5.2/§5.3). Never the "
        "app's own DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = create_db_engine(args.database_url)
    results = run_purge(
        engine,
        retention_days_shadow_findings=settings.RETENTION_DAYS_SHADOW_FINDINGS,
        retention_days_protected_attribute_resolutions=(
            settings.RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS
        ),
    )

    for result in results:
        if result.skipped:
            print(f"SKIP {result.table_name}: no retention window configured")
        else:
            cutoff_text = result.cutoff.isoformat() if result.cutoff is not None else "n/a"
            print(
                f"PURGED {result.table_name}: {result.deleted_count} row(s) older than "
                f"{cutoff_text} ({result.retention_days} day(s))"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
