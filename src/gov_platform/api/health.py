"""Liveness endpoint.

Deliberately minimal since M0: returns process liveness only, unchanged by
M7. The readiness check this docstring used to name as a future gap
(architecture §9) is now real — see `api/readiness.py`'s `GET /readyz`,
additive alongside this endpoint, not a redefinition of it. `/readyz`
checks database reachability only; "adapter/source reachability" (the
other half of the original architecture §9 citation) is currently
vacuous — neither first-party `Adapter` has a real external dependency to
check yet — see `api/readiness.py`'s own docstring and
`docs/milestones/M7.md` §4.1.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def health_check() -> dict[str, str]:
    """Process liveness only — not a readiness/dependency check."""
    return {"status": "HEALTHY"}
