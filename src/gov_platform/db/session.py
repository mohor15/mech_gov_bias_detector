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

M11: `create_db_engine` now normalizes a bare `postgresql://`/`postgres://`
URL to `postgresql+psycopg://` before constructing the engine — found and
fixed after CI failed with `ModuleNotFoundError: No module named
'psycopg2'` the moment `tests/conftest.py`'s new `admin_db_engine` fixture
(and `retention/purge_expired_records.py`'s CLI, which calls this same
function) first passed a bare-scheme `ADMIN_DATABASE_URL` through here.
SQLAlchemy's own default dialect for a bare `postgresql://` scheme is
`psycopg2`, which isn't a dependency of this project (only `psycopg`, v3,
is) and isn't installed. `db/migrate.py` solved this identical problem for
its own `--database-url` argument at M1 (`_with_psycopg_driver`, moved
here so every caller of this function is protected, not just that one CLI)
— `ADMIN_DATABASE_URL` is deliberately a bare-scheme URL because it's also
handed directly to `psycopg.connect()` by `infra/ci/setup_test_role.py`,
which needs the plain scheme, not a SQLAlchemy dialect suffix, so the env
var itself can't just be rewritten instead.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

# Generous enough that a real, merely-slow-to-accept database (e.g. under
# load) is not mistaken for unreachable, tight enough that a genuinely
# unreachable host fails within a readiness probe's own realistic budget,
# not the OS's full TCP-retransmission timeout (measured well over a
# minute on a genuinely dropped connection during this milestone's own
# implementation).
_CONNECT_TIMEOUT_SECONDS = 5


def with_psycopg_driver(database_url: str) -> str:
    """Force the `psycopg` (v3) driver for a bare `postgresql://`/
    `postgres://` URL — see this module's own docstring for the full
    reasoning. A no-op for any URL that already names a driver
    (`postgresql+psycopg://`, or any other explicit dialect)."""
    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return str(url.render_as_string(hide_password=False))


def create_db_engine(database_url: str) -> Engine:
    return create_engine(
        with_psycopg_driver(database_url),
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )
