"""Verdict Reviews Admin API — architecture §12, M9 (Human Review Workflow).

Gives an `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` `GovernanceVerdict` (M5)
somewhere to go: list/inspect the queue, claim an item, release an
abandoned claim, and resolve it. Manages workflow state *about* an
already-computed, already-immutable `Verdict` — it never creates one, the
same "this API manages facts, it never loads new code or computes new
results" boundary every other Admin API in this codebase draws, applied
here to workflow state rather than to configuration.

Each list/get response embeds the full `GovernanceVerdict` (findings and
all) so a caller has everything needed to actually review the item in one
request, without this milestone inventing a first-ever generic "list/get a
`Verdict`" endpoint nothing before M9 has ever needed
(`VerdictRepository` has only `get`/`create`/`get_many` — no unscoped
`list_all` — see `docs/milestones/M9.md` §4.5). The list endpoint's
embedded `Verdict`s are fetched via `VerdictRepository.get_many`, not a
per-row loop calling `get()` — an N+1 query pattern found during M9's own
hostile-review pass (§3.7/§7).

`claim`/`release`/`resolve` each translate a domain-level `ValueError`
(raised by `VerdictReviewRepository` for a conditional-`UPDATE` that
affected zero rows — wrong status, or, for `resolve`, a `reviewer` that
doesn't match who claimed it) into a `409`, via an explicit `try`/`except`
in this module — **not** by letting the `ValueError` propagate to
`api/app.py`'s global handler, which defaults any uncaught `ValueError` to
`422` (the existing, accepted behavior for e.g.
`PluginRegistrationRepository.promote`). A conflict here is a concurrency
outcome, not a request-validation failure, so it gets its own explicit
translation instead of falling through to that default.

Handlers are plain `def`, not `async def` — same reasoning as every other
route in this codebase.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.admin._shared import resolve_reviewer
from gov_platform.api.dependencies import (
    get_db_engine,
    get_verdict_repository,
    get_verdict_review_repository,
    require_role,
)
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.schemas.human_review import (
    VerdictReview,
    VerdictReviewResolution,
    VerdictReviewStatus,
)
from gov_platform.schemas.principal import Principal, PrincipalRole
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus

router = APIRouter(tags=["admin"])

# Bound once, at module scope -- not called inline inside a signature's own
# default value (ruff B008 flags a nested function call there even though
# `Depends` itself is allowlisted; see pyproject.toml's own
# extend-immutable-calls comment).
_require_reviewer_or_admin = require_role(PrincipalRole.REVIEWER, PrincipalRole.ADMIN)


class VerdictReviewResponse(BaseModel):
    id: str
    verdict_id: str
    status: VerdictReviewStatus
    reviewer: str | None
    resolution: VerdictReviewResolution | None
    resolution_notes: str | None
    created_at: datetime
    claimed_at: datetime | None
    resolved_at: datetime | None
    verdict: GovernanceVerdict


class ClaimVerdictReviewRequest(BaseModel):
    # M13: optional, not required -- a backward-compatible relaxation.
    # Once a caller is authenticated, the persisted reviewer is always
    # the authenticated principal's own name, never this field; a
    # present-but-disagreeing value is rejected, never silently
    # discarded. See api/admin/_shared.resolve_reviewer and
    # docs/milestones/M13.md §5.6.
    reviewer: str | None = Field(default=None, min_length=1)


class ResolveVerdictReviewRequest(BaseModel):
    reviewer: str | None = Field(default=None, min_length=1)
    resolution: VerdictReviewResolution
    notes: str = Field(..., min_length=1)


def _to_response(review: VerdictReview, verdict: GovernanceVerdict) -> VerdictReviewResponse:
    return VerdictReviewResponse(
        id=review.id,
        verdict_id=review.verdict_id,
        status=review.status,
        reviewer=review.reviewer,
        resolution=review.resolution,
        resolution_notes=review.resolution_notes,
        created_at=review.created_at,
        claimed_at=review.claimed_at,
        resolved_at=review.resolved_at,
        verdict=verdict,
    )


@router.get(
    "/verdict-reviews",
    response_model=list[VerdictReviewResponse],
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def list_verdict_reviews(
    status_filter: VerdictReviewStatus | None = Query(default=None, alias="status"),
    severity: VerdictStatus | None = Query(default=None),
    limit: int | None = Query(default=None, gt=0, le=1000),
    offset: int | None = Query(default=None, ge=0),
    engine: Engine = Depends(get_db_engine),
    verdict_review_repository: VerdictReviewRepository = Depends(get_verdict_review_repository),
    verdict_repository: VerdictRepository = Depends(get_verdict_repository),
) -> list[VerdictReviewResponse]:
    """M15: `limit`/`offset` are optional and unbounded by default --
    omitting both returns every matching row, exactly as before this
    milestone (`docs/milestones/M15.md` §12.1 option (a))."""
    with Session(engine) as session:
        reviews = verdict_review_repository.list_all(
            session, status=status_filter, severity=severity, limit=limit, offset=offset
        )
        verdicts_by_id = verdict_repository.get_many(session, [r.verdict_id for r in reviews])

    return [_to_response(review, verdicts_by_id[review.verdict_id]) for review in reviews]


@router.get(
    "/verdict-reviews/{review_id}",
    response_model=VerdictReviewResponse,
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def get_verdict_review(
    review_id: str,
    engine: Engine = Depends(get_db_engine),
    verdict_review_repository: VerdictReviewRepository = Depends(get_verdict_review_repository),
    verdict_repository: VerdictRepository = Depends(get_verdict_repository),
) -> VerdictReviewResponse:
    with Session(engine) as session:
        review = verdict_review_repository.get(session, review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="verdict review not found"
            )
        verdict = verdict_repository.get(session, review.verdict_id)

    assert verdict is not None  # verdict_id is a real FK -- see migration 0023
    return _to_response(review, verdict)


@router.post("/verdict-reviews/{review_id}/claim", response_model=VerdictReviewResponse)
def claim_verdict_review(
    review_id: str,
    payload: ClaimVerdictReviewRequest,
    engine: Engine = Depends(get_db_engine),
    verdict_review_repository: VerdictReviewRepository = Depends(get_verdict_review_repository),
    verdict_repository: VerdictRepository = Depends(get_verdict_repository),
    principal: Principal | None = Depends(_require_reviewer_or_admin),
) -> VerdictReviewResponse:
    reviewer = resolve_reviewer(payload.reviewer, principal)
    with Session(engine) as session:
        if verdict_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="verdict review not found"
            )
        try:
            review = verdict_review_repository.claim(session, review_id, reviewer)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        verdict = verdict_repository.get(session, review.verdict_id)

    assert verdict is not None  # verdict_id is a real FK -- see migration 0023
    return _to_response(review, verdict)


@router.post(
    "/verdict-reviews/{review_id}/release",
    response_model=VerdictReviewResponse,
    dependencies=[Depends(_require_reviewer_or_admin)],
)
def release_verdict_review(
    review_id: str,
    engine: Engine = Depends(get_db_engine),
    verdict_review_repository: VerdictReviewRepository = Depends(get_verdict_review_repository),
    verdict_repository: VerdictRepository = Depends(get_verdict_repository),
) -> VerdictReviewResponse:
    with Session(engine) as session:
        if verdict_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="verdict review not found"
            )
        try:
            review = verdict_review_repository.release(session, review_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        verdict = verdict_repository.get(session, review.verdict_id)

    assert verdict is not None  # verdict_id is a real FK -- see migration 0023
    return _to_response(review, verdict)


@router.post("/verdict-reviews/{review_id}/resolve", response_model=VerdictReviewResponse)
def resolve_verdict_review(
    review_id: str,
    payload: ResolveVerdictReviewRequest,
    engine: Engine = Depends(get_db_engine),
    verdict_review_repository: VerdictReviewRepository = Depends(get_verdict_review_repository),
    verdict_repository: VerdictRepository = Depends(get_verdict_repository),
    principal: Principal | None = Depends(_require_reviewer_or_admin),
) -> VerdictReviewResponse:
    reviewer = resolve_reviewer(payload.reviewer, principal)
    with Session(engine) as session:
        if verdict_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="verdict review not found"
            )
        try:
            review = verdict_review_repository.resolve(
                session,
                review_id,
                reviewer=reviewer,
                resolution=payload.resolution,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        verdict = verdict_repository.get(session, review.verdict_id)

    assert verdict is not None  # verdict_id is a real FK -- see migration 0023
    return _to_response(review, verdict)
