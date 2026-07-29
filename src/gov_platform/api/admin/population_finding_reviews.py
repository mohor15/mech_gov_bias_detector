"""Population Finding Reviews Admin API — architecture §12, M9 (Human
Review Workflow).

Mirrors `api/admin/verdict_reviews.py` exactly, for a `FLAGGED`
`PopulationFinding` (M6/M8) instead of a `GovernanceVerdict` (M5) — see
that module's docstring for the full reasoning behind embedding the full
subject in each response, and translating a `ValueError` conflict into a
`409` via an explicit `try`/`except` rather than letting it fall through
to `api/app.py`'s global handler (which defaults to `422`).

No `severity` filter on the list endpoint — unlike `VerdictStatus`,
`PopulationFindingOutcome` is already binary (`CLEAR`/`FLAGGED`), with no
severity tier to filter by; every queued item here is already `FLAGGED`
by construction. No new batch-fetch method was needed on
`PopulationFindingRepository` for this endpoint's embedded data (unlike
`VerdictRepository.get_many`, added for the verdict-reviews list
endpoint): `PopulationFindingRepository.get` is already a single indexed
primary-key lookup, not a multi-table join, so a per-row loop here is not
the same N+1 concern (`docs/milestones/M9.md` §5.1 scopes the new
batch-fetch method to `VerdictRepository` specifically).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import (
    get_db_engine,
    get_population_finding_repository,
    get_population_finding_review_repository,
)
from gov_platform.db.repositories.population_finding import (
    PopulationFindingRecord,
    PopulationFindingRepository,
)
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.schemas.human_review import (
    PopulationFindingReview,
    PopulationFindingReviewResolution,
    PopulationFindingReviewStatus,
)

router = APIRouter(tags=["admin"])


class PopulationFindingReviewResponse(BaseModel):
    id: str
    population_finding_id: str
    status: PopulationFindingReviewStatus
    reviewer: str | None
    resolution: PopulationFindingReviewResolution | None
    resolution_notes: str | None
    created_at: datetime
    claimed_at: datetime | None
    resolved_at: datetime | None
    population_finding: PopulationFindingRecord


class ClaimPopulationFindingReviewRequest(BaseModel):
    reviewer: str = Field(..., min_length=1)


class ResolvePopulationFindingReviewRequest(BaseModel):
    reviewer: str = Field(..., min_length=1)
    resolution: PopulationFindingReviewResolution
    notes: str = Field(..., min_length=1)


def _to_response(
    review: PopulationFindingReview, population_finding: PopulationFindingRecord
) -> PopulationFindingReviewResponse:
    return PopulationFindingReviewResponse(
        id=review.id,
        population_finding_id=review.population_finding_id,
        status=review.status,
        reviewer=review.reviewer,
        resolution=review.resolution,
        resolution_notes=review.resolution_notes,
        created_at=review.created_at,
        claimed_at=review.claimed_at,
        resolved_at=review.resolved_at,
        population_finding=population_finding,
    )


@router.get("/population-finding-reviews", response_model=list[PopulationFindingReviewResponse])
def list_population_finding_reviews(
    status_filter: PopulationFindingReviewStatus | None = Query(default=None, alias="status"),
    engine: Engine = Depends(get_db_engine),
    population_finding_review_repository: PopulationFindingReviewRepository = Depends(
        get_population_finding_review_repository
    ),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> list[PopulationFindingReviewResponse]:
    with Session(engine) as session:
        reviews = population_finding_review_repository.list_all(session, status=status_filter)
        responses = []
        for review in reviews:
            population_finding = population_finding_repository.get(
                session, review.population_finding_id
            )
            assert population_finding is not None  # population_finding_id is a real FK
            responses.append(_to_response(review, population_finding))

    return responses


@router.get(
    "/population-finding-reviews/{review_id}", response_model=PopulationFindingReviewResponse
)
def get_population_finding_review(
    review_id: str,
    engine: Engine = Depends(get_db_engine),
    population_finding_review_repository: PopulationFindingReviewRepository = Depends(
        get_population_finding_review_repository
    ),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> PopulationFindingReviewResponse:
    with Session(engine) as session:
        review = population_finding_review_repository.get(session, review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="population finding review not found"
            )
        population_finding = population_finding_repository.get(
            session, review.population_finding_id
        )

    assert population_finding is not None  # population_finding_id is a real FK
    return _to_response(review, population_finding)


@router.post(
    "/population-finding-reviews/{review_id}/claim", response_model=PopulationFindingReviewResponse
)
def claim_population_finding_review(
    review_id: str,
    payload: ClaimPopulationFindingReviewRequest,
    engine: Engine = Depends(get_db_engine),
    population_finding_review_repository: PopulationFindingReviewRepository = Depends(
        get_population_finding_review_repository
    ),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> PopulationFindingReviewResponse:
    with Session(engine) as session:
        if population_finding_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="population finding review not found"
            )
        try:
            review = population_finding_review_repository.claim(
                session, review_id, payload.reviewer
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        population_finding = population_finding_repository.get(
            session, review.population_finding_id
        )

    assert population_finding is not None  # population_finding_id is a real FK
    return _to_response(review, population_finding)


@router.post(
    "/population-finding-reviews/{review_id}/release",
    response_model=PopulationFindingReviewResponse,
)
def release_population_finding_review(
    review_id: str,
    engine: Engine = Depends(get_db_engine),
    population_finding_review_repository: PopulationFindingReviewRepository = Depends(
        get_population_finding_review_repository
    ),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> PopulationFindingReviewResponse:
    with Session(engine) as session:
        if population_finding_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="population finding review not found"
            )
        try:
            review = population_finding_review_repository.release(session, review_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        population_finding = population_finding_repository.get(
            session, review.population_finding_id
        )

    assert population_finding is not None  # population_finding_id is a real FK
    return _to_response(review, population_finding)


@router.post(
    "/population-finding-reviews/{review_id}/resolve",
    response_model=PopulationFindingReviewResponse,
)
def resolve_population_finding_review(
    review_id: str,
    payload: ResolvePopulationFindingReviewRequest,
    engine: Engine = Depends(get_db_engine),
    population_finding_review_repository: PopulationFindingReviewRepository = Depends(
        get_population_finding_review_repository
    ),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> PopulationFindingReviewResponse:
    with Session(engine) as session:
        if population_finding_review_repository.get(session, review_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="population finding review not found"
            )
        try:
            review = population_finding_review_repository.resolve(
                session,
                review_id,
                reviewer=payload.reviewer,
                resolution=payload.resolution,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        session.commit()
        population_finding = population_finding_repository.get(
            session, review.population_finding_id
        )

    assert population_finding is not None  # population_finding_id is a real FK
    return _to_response(review, population_finding)
