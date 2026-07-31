"""The compliance report's own model and bounded-window query functions —
architecture §14, M12.

Reuses *shape*, not code, from `observability/metrics.py` (M7):
`VerdictCounts.by_status`/`FindingCounts.by_policy`/
`PopulationFindingCounts.by_policy` intentionally mirror
`GovernanceHealthMetrics`'s own field names and nesting, so an operator who
already understands M7's live endpoint's response shape recognizes this
report's shape immediately. What is *not* shared: this module never
imports from, or modifies, `observability/metrics.py` itself.
`get_governance_health_metrics(engine, *, since)` computes an open-ended
`[since, now())` window (`window_end = datetime.now(UTC)`, unconditionally)
— a monthly compliance report needs a *closed* `[window_start, window_end)`
window with both ends fixed in the past, a genuinely different windowing
shape M7's own function was never designed to answer. Retrofitting a second
upper-bound parameter onto it would mean reopening a module this project's
own standing discipline (M8 §13.14, M9 §9.1, M11 §4.3) has repeatedly
declined to reopen for an unrelated milestone's need — see
`docs/milestones/M12.md` §4.1/§5.2/§12.3.

Content is deliberately scoped to exactly five tables — `verdicts`,
`findings`, `population_findings`, `verdict_reviews`,
`population_finding_reviews` — none of which is retention-eligible (M11
§5.2 names `shadow_findings`/`protected_attribute_resolutions` as the only
two) and none of which is ever deleted from in practice
(`verdict_reviews`/`population_finding_reviews` retain ordinary `DELETE`
privilege but no write path in this codebase ever calls it). A report for a
given historical window is therefore guaranteed byte-reproducible on
regeneration, with no undisclosed-drift caveat needed — see
`docs/milestones/M12.md` §4.3/§5.1/§12.2.

No free text anywhere in this model (no `rationale`, no `resolution_notes`,
no `reviewer`) — a deliberate scoping choice that makes encryption (M11) a
complete non-issue (`resolution_notes` is the only M11-encrypted column on
either review table, and it is never read here) and substantially narrows
CSV-injection exposure (§5.5). `policy_id`/`population_policy_id` are
genuine free-form strings (operator/plugin-author-configured, not
attacker-reachable via the unauthenticated ingestion surface the way
`resolution_notes` is) rather than values from a closed enum — named
explicitly, not overclaimed as "fixed enum-value keys only," per M12's own
second hostile-review pass.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Two real, Postgres-only defects found by direct execution against a real
# database (never caught by ruff/mypy/pytest-without-Postgres, since none
# of those parse or run SQL text): (1) the inner `SELECT id FROM
# decision_events de JOIN model_versions mv ...` was ambiguous -- both
# tables have their own `id` primary key column, so bare `id` needed
# qualifying as `de.id`, the specific one this subquery actually means.
# (2) `:system_id IS NULL` alone gave Postgres's extended query protocol no
# type to bind that parameter occurrence to (`IS NULL` accepts any type),
# raising `AmbiguousParameter: could not determine data type of parameter`
# -- fixed by `CAST(:system_id AS text) IS NULL`, which gives that one
# occurrence an explicit type without touching the other occurrence (`...
# = :system_id`), whose type is already inferred from the column it's
# compared against.
_VERDICT_COUNTS_SQL = text(
    """
    SELECT status, COUNT(*) AS count
    FROM verdicts
    WHERE created_at >= :window_start AND created_at < :window_end
      AND (CAST(:system_id AS text) IS NULL OR decision_event_id IN (
          SELECT de.id FROM decision_events de
          JOIN model_versions mv ON mv.id = de.model_version_id
          WHERE mv.system_id = :system_id
      ))
    GROUP BY status
    """
)

_FINDING_COUNTS_SQL = text(
    """
    SELECT policy_id, outcome, COUNT(*) AS count
    FROM findings
    WHERE evaluated_at >= :window_start AND evaluated_at < :window_end
      AND (CAST(:system_id AS text) IS NULL OR decision_event_id IN (
          SELECT de.id FROM decision_events de
          JOIN model_versions mv ON mv.id = de.model_version_id
          WHERE mv.system_id = :system_id
      ))
    GROUP BY policy_id, outcome
    """
)

# population_findings already carries system_id directly (M6) -- no
# decision_events/model_versions join needed for this one, unlike the two
# above (see this module's own docstring and docs/milestones/M12.md §5.1).
_POPULATION_FINDING_COUNTS_SQL = text(
    """
    SELECT population_policy_id, outcome, COUNT(*) AS count
    FROM population_findings
    WHERE evaluated_at >= :window_start AND evaluated_at < :window_end
      AND (CAST(:system_id AS text) IS NULL OR system_id = :system_id)
    GROUP BY population_policy_id, outcome
    """
)

_REVIEW_OUTCOME_SQL = text(
    """
    SELECT vr.resolution, COUNT(*) AS count
    FROM verdict_reviews vr
    JOIN verdicts v ON v.id = vr.verdict_id
    WHERE vr.status = 'RESOLVED'
      AND vr.resolved_at >= :window_start AND vr.resolved_at < :window_end
      AND (CAST(:system_id AS text) IS NULL OR v.decision_event_id IN (
          SELECT de.id FROM decision_events de
          JOIN model_versions mv ON mv.id = de.model_version_id
          WHERE mv.system_id = :system_id
      ))
    GROUP BY vr.resolution
    """
)

# One join shallower than _REVIEW_OUTCOME_SQL:
# population_finding_reviews.population_finding_id -> population_findings.id,
# which already carries system_id directly (M6).
_POPULATION_FINDING_REVIEW_OUTCOME_SQL = text(
    """
    SELECT pfr.resolution, COUNT(*) AS count
    FROM population_finding_reviews pfr
    JOIN population_findings pf ON pf.id = pfr.population_finding_id
    WHERE pfr.status = 'RESOLVED'
      AND pfr.resolved_at >= :window_start AND pfr.resolved_at < :window_end
      AND (CAST(:system_id AS text) IS NULL OR pf.system_id = :system_id)
    GROUP BY pfr.resolution
    """
)


class VerdictCounts(BaseModel):
    model_config = ConfigDict(frozen=True)
    by_status: dict[str, int]  # VerdictStatus value -> count


class FindingCounts(BaseModel):
    model_config = ConfigDict(frozen=True)
    by_policy: dict[str, dict[str, int]]  # policy_id -> outcome -> count


class PopulationFindingCounts(BaseModel):
    model_config = ConfigDict(frozen=True)
    by_policy: dict[str, dict[str, int]]  # population_policy_id -> outcome -> count


class ReviewOutcomeCounts(BaseModel):
    """Reviews *resolved* within the window -- not reviews *created*
    within it (a review created in one window and resolved in a later one
    is counted in the window it was actually resolved, matching what a
    compliance audience actually wants to know: what got decided during
    this period, not merely what was queued). The two fields below are two
    independently-keyed dicts, not one -- a verdict-review resolution and a
    population-finding-review resolution are different key spaces with no
    shared row shape, and are exported as two separate CSV files, not one
    (see `reporting/generate_report.py`)."""

    model_config = ConfigDict(frozen=True)
    verdict_reviews_by_resolution: dict[str, int]  # 'CONFIRMED' | 'DISMISSED' -> count
    population_finding_reviews_by_resolution: dict[str, int]


class ComplianceReport(BaseModel):
    """A read-time view with no backing row -- the identical relationship
    `MetricsResponse` (M7) has to a live query, applied to a closed,
    historical window instead of an open-ended one. Deliberately not
    persisted anywhere in this platform."""

    model_config = ConfigDict(frozen=True)

    window_start: datetime
    window_end: datetime
    system_id: str | None  # None means "platform-wide, all systems"
    verdicts: VerdictCounts
    findings: FindingCounts
    population_findings: PopulationFindingCounts
    reviews: ReviewOutcomeCounts
    generated_at: datetime


def get_compliance_report(
    engine: Engine,
    *,
    window_start: datetime,
    window_end: datetime,
    system_id: str | None = None,
) -> ComplianceReport:
    """Runs all five queries inside one `REPEATABLE READ` transaction — the
    identical concurrency reasoning `population_engine/window.py` already
    established (M6 §13.13) for a multi-statement read over tables that can
    change between statements: a report whose own five counts were read
    under five different, silently-inconsistent snapshots (a verdict
    included in one count but its matching review resolution missed by a
    narrower/later snapshot) would be a real, avoidable correctness gap for
    a document whose entire purpose is being trusted at face value."""
    params = {"window_start": window_start, "window_end": window_end, "system_id": system_id}

    with Session(engine) as session:
        # Must be set before the first query -- SQLAlchemy opens the
        # underlying transaction lazily, on first use, at whatever
        # isolation level is configured at that point.
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        verdict_counts: dict[str, int] = dict(
            session.execute(_VERDICT_COUNTS_SQL, params).all()  # type: ignore[arg-type]
        )

        finding_counts: dict[str, dict[str, int]] = {}
        for policy_id, outcome, count in session.execute(_FINDING_COUNTS_SQL, params):
            finding_counts.setdefault(policy_id, {})[outcome] = count

        population_finding_counts: dict[str, dict[str, int]] = {}
        for population_policy_id, outcome, count in session.execute(
            _POPULATION_FINDING_COUNTS_SQL, params
        ):
            population_finding_counts.setdefault(population_policy_id, {})[outcome] = count

        verdict_review_counts: dict[str, int] = dict(
            session.execute(_REVIEW_OUTCOME_SQL, params).all()  # type: ignore[arg-type]
        )
        population_finding_review_counts: dict[str, int] = dict(
            session.execute(  # type: ignore[arg-type]
                _POPULATION_FINDING_REVIEW_OUTCOME_SQL, params
            ).all()
        )

    return ComplianceReport(
        window_start=window_start,
        window_end=window_end,
        system_id=system_id,
        verdicts=VerdictCounts(by_status=verdict_counts),
        findings=FindingCounts(by_policy=finding_counts),
        population_findings=PopulationFindingCounts(by_policy=population_finding_counts),
        reviews=ReviewOutcomeCounts(
            verdict_reviews_by_resolution=verdict_review_counts,
            population_finding_reviews_by_resolution=population_finding_review_counts,
        ),
        generated_at=datetime.now(UTC),
    )
