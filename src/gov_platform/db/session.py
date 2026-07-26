"""Database engine construction.

One `Engine` per process, shared across the Evidence Store and the Admin
API's repositories — building a separate engine per component would mean
separate connection pools for no benefit. `create_engine` is lazy: no
connection is actually opened until something first queries through it, so
constructing this at app-startup does not require a live database (see
`api.app.create_app` and the M1 design note on why that matters for M0's
tests that never touch persistence).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url)
