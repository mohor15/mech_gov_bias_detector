"""Population Findings Admin API — architecture §13, M6.

Read-only: `GET`/`GET by id`, optionally filtered by `system_id` — no
`POST`. A population finding is only ever produced by
`population_engine/run_policies.py`'s batch run, never created directly
through this API, the same "this API manages facts, it never loads new
code or computes new results" boundary every other Admin API in this
codebase draws, applied here to computation instead of code.

Diverges from the pure "no query API exists yet for anything" precedent
every other Finding/Verdict table in this codebase follows — see
`docs/milestones/M6.md` §13.12: a population finding with no retrieval
path at all would be exactly the "infrastructure with zero callers"
failure mode `docs/milestones/M2.md` §2 already named and avoided once,
now avoided a second time.

Handlers are plain `def`, not `async def` — same reasoning as every other
route in this codebase.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import get_db_engine, get_population_finding_repository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.schemas.population_finding import PopulationFindingOutcome

router = APIRouter(tags=["admin"])


class PopulationFindingResponse(BaseModel):
    id: str
    population_policy_id: str
    population_policy_version: str
    system_id: str
    window_start: datetime
    window_end: datetime
    outcome: PopulationFindingOutcome
    metric_values: dict[str, float]
    classification_snapshot: dict[str, str]
    rationale: str
    evaluated_at: datetime
    signature: str | None
    signing_key_id: str | None


@router.get("/population-findings", response_model=list[PopulationFindingResponse])
def list_population_findings(
    system_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, gt=0, le=1000),
    offset: int | None = Query(default=None, ge=0),
    engine: Engine = Depends(get_db_engine),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> list[PopulationFindingResponse]:
    """M15: `limit`/`offset` are optional and unbounded by default --
    omitting both returns every matching row, exactly as before this
    milestone (`docs/milestones/M15.md` §12.1 option (a))."""
    with Session(engine) as session:
        findings = (
            population_finding_repository.list_for_system(
                session, system_id, limit=limit, offset=offset
            )
            if system_id is not None
            else population_finding_repository.list_all(session, limit=limit, offset=offset)
        )
    return [PopulationFindingResponse(**f.model_dump()) for f in findings]


@router.get("/population-findings/{finding_id}", response_model=PopulationFindingResponse)
def get_population_finding(
    finding_id: str,
    engine: Engine = Depends(get_db_engine),
    population_finding_repository: PopulationFindingRepository = Depends(
        get_population_finding_repository
    ),
) -> PopulationFindingResponse:
    with Session(engine) as session:
        finding = population_finding_repository.get(session, finding_id)

    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="population finding not found"
        )
    return PopulationFindingResponse(**finding.model_dump())
