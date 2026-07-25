"""Liveness endpoint.

Deliberately minimal in M0: returns process liveness only. A readiness check
that verifies Evidence Store writability and (once they exist) adapter/source
reachability is explicitly called out as a gap to close in later milestones
(architecture §9) — reporting "healthy" without checking dependencies was a
known V1 weakness, not something to quietly repeat here, so this endpoint
is named and scoped narrowly rather than overclaiming readiness it can't
verify yet.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Process liveness only — not a readiness/dependency check."""
    return {"status": "HEALTHY"}
