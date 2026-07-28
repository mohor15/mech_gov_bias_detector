"""Metrics Admin API — architecture §9, M7.

One read-only endpoint assembling `observability/metrics.py`'s queries
into a JSON response — no mutation, no new persisted state, no UI (see
`docs/milestones/M7.md` §4.2/§4.3/§13.2). `since` scopes only the
governance-health half of the response (recent activity); system-health
metrics describe current state and are never windowed — see
`docs/milestones/M7.md` §7's revised note.

Deliberately does not special-case a database failure the way
`api/readiness.py` does: an unreachable database here falls through to
`api/app.py`'s existing generic `Exception` handler (a `500`), the same
behavior every other DB-touching Admin API endpoint already has.
`/readyz`'s `503` answers a different question ("is this instance safe
to route traffic to at all"); an Admin API call failing because its one
dependency is down is an ordinary server error, not a readiness signal —
see `docs/milestones/M7.md` §7's "reviewed, no issue found" note.

Handlers are plain `def`, not `async def` — same reasoning as every
other route in this codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Engine

from gov_platform.api.dependencies import get_db_engine
from gov_platform.observability.metrics import MetricsResponse, get_metrics

router = APIRouter(tags=["admin"])

_DEFAULT_WINDOW = timedelta(hours=24)


def resolve_since(since: datetime | None) -> datetime:
    """Defaults to the last 24 hours; rejects a naive `since` explicitly
    rather than silently guessing a timezone for it. Pulled out as its
    own pure function so this validation is unit-testable without a
    database — see `docs/milestones/M7.md` §10."""
    if since is None:
        return datetime.now(UTC) - _DEFAULT_WINDOW
    if since.tzinfo is None:
        # Same discipline schemas/decision_event.py's own validator
        # already enforces for every persisted timestamp in this
        # codebase, applied here to a query parameter instead --
        # propagates to api/app.py's existing ValueError -> 422 handler.
        raise ValueError("since must be timezone-aware")
    return since


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics_endpoint(
    since: datetime | None = Query(
        default=None,
        description="ISO 8601 timestamp, timezone-aware. Governance-health counts are scoped to "
        "[since, now()). Defaults to the last 24 hours.",
    ),
    engine: Engine = Depends(get_db_engine),
) -> MetricsResponse:
    return get_metrics(engine, since=resolve_since(since))
