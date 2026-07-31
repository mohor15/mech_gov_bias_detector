"""Shared helper between `verdict_reviews.py` and
`population_finding_reviews.py` — architecture (no numbered section; see
`docs/milestones/M13.md` Sourcing note), M13.

Extracted once a second real caller appeared *within this same
milestone* — the identical "three similar lines beat a premature shared
abstraction, until a second real caller shows up" discipline
`population_engine/policies/_shared.py` (M8) already established.
Private (`_shared`, not part of any router's own public surface),
mirroring that module's own naming convention.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from gov_platform.schemas.principal import Principal


def resolve_reviewer(payload_reviewer: str | None, principal: Principal | None) -> str:
    """Closes `docs/milestones/M9.md`'s own named "fabricated reviewer"
    gap: once a caller is authenticated (`principal` is not `None`), the
    persisted `reviewer` is always the authenticated principal's own
    name, never the request body -- a client-supplied value that
    disagrees with it is rejected with `422`, never silently discarded
    (`docs/milestones/M13.md` §5.6/§9/§13.13). When no principal is
    resolved (`AUTH_ENABLED=false`), behavior is byte-for-byte the
    pre-M13 one: `payload_reviewer` is required, enforced here instead of
    by the request model's own (now-relaxed) `Field(...)`.
    """
    if principal is None:
        if payload_reviewer is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reviewer is required"
            )
        return payload_reviewer

    if payload_reviewer is not None and payload_reviewer != principal.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="reviewer, if provided, must match the authenticated principal",
        )
    return principal.name
