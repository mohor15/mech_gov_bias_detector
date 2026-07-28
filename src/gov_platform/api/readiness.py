"""Readiness endpoint — architecture §9, M7.

`api/health.py`'s own docstring named this exact gap since M0:
"reporting 'healthy' without checking dependencies was a known V1
weakness." `/healthz` stays exactly as M0 built it (process liveness
only, zero dependency); `/readyz` is new and additive, checking a real
(if minimal) database round trip — see `docs/milestones/M7.md` §4.1/§13.3
for why this is a second endpoint, not a redefinition of `/healthz`'s
existing, already-depended-on meaning.

Deliberately a read-only connectivity check (`observability.metrics.check_db_reachable`),
not a literal write against `evidence_chain` — see
`docs/milestones/M7.md` §13.7. Deliberately database-connectivity-only,
not also checking "adapter/source reachability" (the other half of
`api/health.py`'s own citation) — neither first-party `Adapter` has a
real external dependency to check yet (`adapters/credit_scorecard.py`:
"there is none to connect to yet"); see `docs/milestones/M7.md` §4.1's
revised note.

Plain `def`, not `async def` — this handler does real, synchronous
database I/O (via SQLAlchemy's synchronous engine), and FastAPI runs a
plain `def` route in a thread pool rather than the event loop. Using
`async def` here would block the event loop under concurrent load, the
exact M0 finalization-review mistake ("Ingestion route ran fully
synchronous code inside `async def`") this codebase has never repeated
since — `api/health.py`'s own `async def` is safe only because it does
zero I/O; this handler is not in that position.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.engine import Engine

from gov_platform.api.dependencies import get_db_engine
from gov_platform.observability.metrics import check_db_reachable

router = APIRouter(tags=["health"])


@router.get("/readyz")
def readiness_check(engine: Engine = Depends(get_db_engine)) -> dict[str, str]:
    """`200` if the database is reachable, `503` otherwise — an
    orchestrator's readiness probe, not process liveness (`/healthz`
    already covers that)."""
    reachable, _latency_ms = check_db_reachable(engine)
    if not reachable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unreachable"
        )
    return {"status": "READY"}
