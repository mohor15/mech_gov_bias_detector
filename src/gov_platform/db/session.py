"""Database engine construction.

One `Engine` per process, shared across the Evidence Store and the Admin
API's repositories — building a separate engine per component would mean
separate connection pools for no benefit. `create_engine` is lazy: no
connection is actually opened until something first queries through it, so
constructing this at app-startup does not require a live database (see
`api.app.create_app` and the M1 design note on why that matters for M0's
tests that never touch persistence).

M7: a bounded connection timeout, found necessary while implementing
`observability.metrics.check_db_reachable` (the query `/readyz` and
`/v1/admin/metrics` both depend on) — verified directly, not assumed:
connecting to a genuinely unreachable host (a dropped route, a closed
security group — not merely "connection refused", which fails fast on its
own) can hang for the OS's full TCP-retransmission timeout, which on this
development machine measured well past a minute. An unbounded readiness
check is worse than no readiness check at all — the one thing `/readyz`
must never do is take longer to fail than the orchestrator polling it is
willing to wait (`docs/milestones/M7.md` §12's "`/readyz` must stay
cheap", extended here from "cheap query" to "cheap to even attempt").
`connect_timeout` is a real `psycopg`/libpq connection parameter (distinct
from a query timeout), bounding only the TCP-connect phase — a healthy
connection to a reachable database is unaffected.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Generous enough that a real, merely-slow-to-accept database (e.g. under
# load) is not mistaken for unreachable, tight enough that a genuinely
# unreachable host fails within a readiness probe's own realistic budget,
# not the OS's full TCP-retransmission timeout (measured well over a
# minute on a genuinely dropped connection during this milestone's own
# implementation).
_CONNECT_TIMEOUT_SECONDS = 5


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS})
