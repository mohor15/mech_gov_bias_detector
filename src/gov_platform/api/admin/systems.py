"""System registration — architecture §15/§16, M1.

Explicit registration here is a *stricter* sibling of the auto-provisioning
`EvidenceStore.append` does internally (see its module docstring): posting
the same name twice through this endpoint is a 409, because an admin
explicitly re-registering a system is more likely a mistake worth surfacing
than a benign no-op. Ingestion's auto-provisioning stays silently
idempotent by design — those are different callers with different intent.

Handlers are plain `def`, not `async def` — same reasoning as the ingestion
route (see its docstring and the M0 finalization review): every operation
here is synchronous, so `async def` would block the event loop instead of
running in FastAPI's threadpool.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import get_db_engine, get_system_repository, require_role
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.principal import PrincipalRole

router = APIRouter(tags=["admin"])


class SystemRegistrationRequest(BaseModel):
    name: str
    domain: str | None = None
    risk_tier: str | None = None
    owner: str | None = None


class SystemResponse(BaseModel):
    id: str
    name: str
    domain: str | None
    risk_tier: str | None
    owner: str | None
    created_at: datetime


@router.post(
    "/systems",
    response_model=SystemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
)
def register_system(
    payload: SystemRegistrationRequest,
    engine: Engine = Depends(get_db_engine),
    system_repository: SystemRepository = Depends(get_system_repository),
) -> SystemResponse:
    with Session(engine) as session:
        if system_repository.get_by_name(session, payload.name) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"system '{payload.name}' is already registered",
            )
        system = system_repository.create(
            session,
            name=payload.name,
            domain=payload.domain,
            risk_tier=payload.risk_tier,
            owner=payload.owner,
        )
        session.commit()

    return SystemResponse(**system.model_dump())


@router.get(
    "/systems",
    response_model=list[SystemResponse],
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def list_systems(
    engine: Engine = Depends(get_db_engine),
    system_repository: SystemRepository = Depends(get_system_repository),
) -> list[SystemResponse]:
    with Session(engine) as session:
        systems = system_repository.list(session)
    return [SystemResponse(**system.model_dump()) for system in systems]


@router.get(
    "/systems/{system_id}",
    response_model=SystemResponse,
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def get_system(
    system_id: str,
    engine: Engine = Depends(get_db_engine),
    system_repository: SystemRepository = Depends(get_system_repository),
) -> SystemResponse:
    with Session(engine) as session:
        system = system_repository.get(session, system_id)

    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="system not found")

    return SystemResponse(**system.model_dump())
