"""System- and governance-health metrics — architecture §9, M7.

The "Monitoring" read pattern this milestone builds — the direct
architectural sibling of M6's own "Event Lake" (`population_engine/window.py`):
no new storage, no new metrics-store technology, just a new, windowed
query pattern over tables every prior milestone already produces
(`verdicts`, `findings`, `shadow_findings`, `population_findings`,
`plugin_registrations`, `population_policy_bindings`, `evidence_chain`).
See `docs/milestones/M7.md` §4.2/§13.1 for the full reasoning behind a
plain, DB-query-backed JSON view rather than Prometheus/OpenTelemetry.

System-health metrics describe *current state* and are never windowed.
Governance-health metrics are scoped to `[since, now())` — an unbounded,
all-time count over `verdicts`/`findings`/`population_findings` (tables
with no retention policy, M11 not built) would get slower without limit
for as long as this platform runs; see `docs/milestones/M7.md` §13.15.

Three things this module is deliberately careful about, each a
hostile-review-pass finding baked into the design before any code was
written (`docs/milestones/M7.md` §13.16/§13.17/§4.2):

1. `evidence_chain`'s size is read via `ORDER BY sequence_number DESC
   LIMIT 1` (the same access pattern `EvidenceStore._latest_hash` already
   uses), never `COUNT(*)` — Postgres has no O(1) row count under MVCC,
   and `evidence_chain` is the one table in this schema that's permanent
   and never shrinks.
2. Population-binding staleness is a `LEFT JOIN` anchored on
   `population_policy_bindings` (filtered to `ACTIVE`), never an
   aggregate starting from `population_findings` — otherwise a binding
   that has never once produced a finding is silently absent from the
   result instead of showing the loudest possible staleness signal
   (`None`).
3. Shadow/production disagreement is computed via
   `shadow_findings.plugin_registration_id -> plugin_registrations.plugin_id`,
   matched back to `findings` on `decision_event_id` — `shadow_findings`
   has no `policy_id` column of its own. A policy family with zero
   comparable (shadow, production) pairs in the window is omitted from
   `shadow_disagreement_rate_by_policy` entirely, not reported as a
   misleading `0.0` or divided by zero.

No new port, no new table — a concrete module of plain query functions,
the same shape `protected_attributes/resolver.py` and
`population_engine/window.py` already are (`docs/milestones/M7.md` §9).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gov_platform.db.models import EvidenceChainRow

_STALENESS_SQL = text(
    """
    SELECT ppb.id AS binding_id, MAX(pf.evaluated_at) AS last_evaluated_at
    FROM population_policy_bindings ppb
    LEFT JOIN population_findings pf
        ON pf.population_policy_id = ppb.population_policy_id
        AND pf.system_id = ppb.system_id
    WHERE ppb.lifecycle_state = 'ACTIVE'
    GROUP BY ppb.id
    """
)

_PLUGIN_COUNTS_SQL = text(
    """
    SELECT plugin_type, lifecycle_state, COUNT(*) AS count
    FROM plugin_registrations
    GROUP BY plugin_type, lifecycle_state
    """
)

_VERDICT_COUNTS_SQL = text(
    """
    SELECT status, COUNT(*) AS count
    FROM verdicts
    WHERE created_at >= :since
    GROUP BY status
    """
)

_FINDING_COUNTS_SQL = text(
    """
    SELECT policy_id, outcome, COUNT(*) AS count
    FROM findings
    WHERE evaluated_at >= :since
    GROUP BY policy_id, outcome
    """
)

_POPULATION_FINDING_COUNTS_SQL = text(
    """
    SELECT population_policy_id, outcome, COUNT(*) AS count
    FROM population_findings
    WHERE evaluated_at >= :since
    GROUP BY population_policy_id, outcome
    """
)

# comparable_count only counts shadow findings that actually have a
# matching production Finding for the same decision_event_id/policy_id
# (an inner-join-shaped COUNT over a LEFT JOIN, via COUNT(f.id) rather
# than COUNT(*)) -- a shadow finding with no production counterpart to
# compare against contributes to neither the numerator nor the
# denominator, rather than being miscounted as either "agreement" or
# "disagreement" it never actually was.
_SHADOW_DISAGREEMENT_SQL = text(
    """
    SELECT
        pr.plugin_id AS policy_id,
        COUNT(f.id) AS comparable_count,
        COUNT(*) FILTER (WHERE sf.outcome != f.outcome) AS disagreement_count
    FROM shadow_findings sf
    JOIN plugin_registrations pr ON pr.id = sf.plugin_registration_id
    LEFT JOIN findings f
        ON f.decision_event_id = sf.decision_event_id
        AND f.policy_id = pr.plugin_id
    WHERE sf.evaluated_at >= :since
    GROUP BY pr.plugin_id
    """
)


class SystemHealthMetrics(BaseModel):
    """Current-state operational signal -- never time-windowed."""

    model_config = ConfigDict(frozen=True)

    db_reachable: bool
    db_latency_ms: float | None
    evidence_chain_latest_sequence_number: int
    plugin_counts: dict[str, dict[str, int]]  # plugin_type -> lifecycle_state -> count
    # binding id -> most recent population_findings.evaluated_at, or None
    # if that ACTIVE binding has never produced a finding at all.
    population_binding_staleness: dict[str, datetime | None]


class GovernanceHealthMetrics(BaseModel):
    """Aggregate signal about governance decisions already made, scoped
    to `[window_start, window_end)`."""

    model_config = ConfigDict(frozen=True)

    window_start: datetime
    window_end: datetime
    verdict_counts_by_status: dict[str, int]
    finding_counts_by_policy: dict[str, dict[str, int]]  # policy_id -> outcome -> count
    population_finding_counts_by_policy: dict[str, dict[str, int]]
    shadow_disagreement_rate_by_policy: dict[str, float]


class MetricsResponse(BaseModel):
    """Deliberately flat, deliberately not persisted -- a read-time view
    with no backing row, the same relationship `EvidenceRecord` has to
    `GovernanceVerdict`, minus the record."""

    model_config = ConfigDict(frozen=True)

    system: SystemHealthMetrics
    governance: GovernanceHealthMetrics
    computed_at: datetime


def disagreement_rate(comparable_count: int, disagreement_count: int) -> float | None:
    """`None` if there is nothing comparable in the window (no production
    finding existed for any shadow finding in this policy family) --
    reported as absent from the response, not a misleading `0.0`, the
    same "insufficient data, not a false signal" discipline
    `population_engine/policies/adverse_impact_ratio.py`'s own
    zero-reference-rate guard already established. Pulled out as its own
    pure function specifically so this shaping logic is unit-testable
    without a database — see `docs/milestones/M7.md` §10.
    """
    if comparable_count == 0:
        return None
    return disagreement_count / comparable_count


def check_db_reachable(engine: Engine) -> tuple[bool, float | None]:
    """A read-only connectivity check -- never a write (see
    `docs/milestones/M7.md` §13.7 on why "writability" is read as "the
    append path is available", not "prove it by writing on every call").
    Never raises: a connection failure is reported as `(False, None)`,
    the same "fail loud to the caller, not to an exception the caller
    didn't ask to catch" shape `/readyz` and this metric both depend on.

    Found during this milestone's own post-implementation hostile
    review: a bare `SELECT 1` (no table involved at all) proves the
    process can authenticate and the network path is open, but proves
    nothing about whether `gov_platform_app`'s actual table-level GRANTs
    are still intact -- a role that could log in but had every grant
    revoked would still report `SELECT 1` successfully, reporting
    "reachable" for a database that would reject every real request this
    platform makes. Reading one real, minimal table (`systems` -- the
    smallest, and the one every ingestion request already touches first,
    via auto-provisioning) closes that gap for negligible extra cost.
    """
    start = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM systems LIMIT 1"))
    except SQLAlchemyError:
        return False, None
    return True, (time.perf_counter() - start) * 1000


def get_system_health_metrics(engine: Engine) -> SystemHealthMetrics:
    db_reachable, db_latency_ms = check_db_reachable(engine)

    with Session(engine) as session:
        latest_sequence_number = (
            session.execute(
                select(EvidenceChainRow.sequence_number)
                .order_by(EvidenceChainRow.sequence_number.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        )

        plugin_counts: dict[str, dict[str, int]] = {}
        for plugin_type, lifecycle_state, count in session.execute(_PLUGIN_COUNTS_SQL):
            plugin_counts.setdefault(plugin_type, {})[lifecycle_state] = count

        population_binding_staleness: dict[str, datetime | None] = {
            binding_id: last_evaluated_at
            for binding_id, last_evaluated_at in session.execute(_STALENESS_SQL)
        }

    return SystemHealthMetrics(
        db_reachable=db_reachable,
        db_latency_ms=db_latency_ms,
        evidence_chain_latest_sequence_number=latest_sequence_number,
        plugin_counts=plugin_counts,
        population_binding_staleness=population_binding_staleness,
    )


def get_governance_health_metrics(engine: Engine, *, since: datetime) -> GovernanceHealthMetrics:
    window_end = datetime.now(UTC)

    with Session(engine) as session:
        verdict_counts_by_status: dict[str, int] = dict(
            session.execute(_VERDICT_COUNTS_SQL, {"since": since}).all()  # type: ignore[arg-type]
        )

        finding_counts_by_policy: dict[str, dict[str, int]] = {}
        for policy_id, outcome, count in session.execute(_FINDING_COUNTS_SQL, {"since": since}):
            finding_counts_by_policy.setdefault(policy_id, {})[outcome] = count

        population_finding_counts_by_policy: dict[str, dict[str, int]] = {}
        for population_policy_id, outcome, count in session.execute(
            _POPULATION_FINDING_COUNTS_SQL, {"since": since}
        ):
            population_finding_counts_by_policy.setdefault(population_policy_id, {})[outcome] = (
                count
            )

        shadow_disagreement_rate_by_policy: dict[str, float] = {}
        for policy_id, comparable_count, disagreement_count in session.execute(
            _SHADOW_DISAGREEMENT_SQL, {"since": since}
        ):
            rate = disagreement_rate(comparable_count, disagreement_count)
            if rate is not None:
                shadow_disagreement_rate_by_policy[policy_id] = rate

    return GovernanceHealthMetrics(
        window_start=since,
        window_end=window_end,
        verdict_counts_by_status=verdict_counts_by_status,
        finding_counts_by_policy=finding_counts_by_policy,
        population_finding_counts_by_policy=population_finding_counts_by_policy,
        shadow_disagreement_rate_by_policy=shadow_disagreement_rate_by_policy,
    )


def get_metrics(engine: Engine, *, since: datetime) -> MetricsResponse:
    return MetricsResponse(
        system=get_system_health_metrics(engine),
        governance=get_governance_health_metrics(engine, since=since),
        computed_at=datetime.now(UTC),
    )
