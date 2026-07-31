"""Compliance Dashboard — architecture §11, M10.

A small set of read-only HTML views rendering data M6/M7/M9 already
compute and already expose via JSON — no new computation, no new
persisted state, no new Admin API surface beyond serving the dashboard's
own static shell (`docs/milestones/M10.md` §1/§4). All three routes below
return the identical static shell HTML file; the client-side JavaScript
(`dashboard_static/dashboard.js`), not this router, decides which view to
render, based on the current path (§4.3).

Registered with `prefix="/dashboard"` and relative route decorators,
matching the `admin_*` router convention (multiple sub-paths sharing one
prefix) rather than `health.py`/`readiness.py`'s single-absolute-route
shape — see `docs/milestones/M10.md` §8.7.

`register_dashboard` (not a bare module-level `router` used directly by
`api/app.py`) exists specifically so `create_app()` can wrap *both* the
`StaticFiles` mount and this router's registration in one `try`/`except`
(`docs/milestones/M10.md` §4.3/§8.6): `StaticFiles(directory=...)` raises
`RuntimeError` at construction time if `_STATIC_DIR` does not exist — the
exact failure mode a real, non-editable install missing `package_data`
declarations produces (§4.4). Without this containment, that packaging
defect would prevent `create_app()` from ever returning an application
object at all, taking `/healthz` down with it — the identical "a failure
in this non-essential subsystem must never take down what matters more"
precedent M9 already established for `_queue_verdict_review`'s own
decoupled transaction (`docs/milestones/M9.md` §3.4), applied here to a
construction-time risk instead of a request-time one.

Handlers are plain `def`, not `async def` — `FileResponse` here does real,
synchronous filesystem I/O (via Starlette's blocking file-stat call),
same reasoning as every other route in this codebase that touches a real
external resource.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "dashboard_static"
_SHELL_HTML = _STATIC_DIR / "index.html"

router = APIRouter(tags=["dashboard"])


@router.get("")
def dashboard_overview() -> FileResponse:
    return FileResponse(_SHELL_HTML)


@router.get("/population-findings")
def dashboard_population_findings() -> FileResponse:
    return FileResponse(_SHELL_HTML)


@router.get("/reviews")
def dashboard_reviews() -> FileResponse:
    return FileResponse(_SHELL_HTML)


def register_dashboard(app: FastAPI, *, dependencies: Sequence[Any] = ()) -> None:
    """Mounts the dashboard's static assets and registers its router.

    Must be called from `create_app()` inside a `try`/`except` — see this
    module's own docstring and `docs/milestones/M10.md` §4.3/§8.6. A
    packaging defect that leaves `_STATIC_DIR` missing in a real,
    non-editable install must degrade to "no dashboard," never "no
    application at all."

    `dependencies` (M13): forwarded to the router's own `include_router`
    call -- `create_app()` passes the "any authenticated principal" role
    check here, a router-level blanket dependency, since all three
    dashboard views share the identical minimum requirement (session
    cookie, any role — `docs/milestones/M13.md` §5.4). The static asset
    *mount* (`login.html` included) is deliberately left unauthenticated:
    a browser must be able to load the login page itself before it has
    any credential to present.
    """
    app.mount("/dashboard/static", StaticFiles(directory=_STATIC_DIR), name="dashboard-static")
    app.include_router(router, prefix="/dashboard", dependencies=list(dependencies))
