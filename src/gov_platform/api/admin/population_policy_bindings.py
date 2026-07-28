"""Population Policy Bindings Admin API — architecture §7/§8, M6.

Manages which `PopulationPolicy` evaluates which `System`'s decisions — a
database fact, changeable without a redeploy. Mirrors
`api/admin/policy_bindings.py`'s shape (`POST`/`GET`/`GET by id`/
`activate`/`deactivate`), keyed by `system_id` instead of `adapter_id` —
see `schemas/population_policy_binding.py` and `docs/milestones/M6.md`
§13.8 for why this is a real, separate key decision, not a copy-paste.

`system_id` must reference an existing `systems` row (a real foreign key,
migration `0014`) and `population_policy_id` must already be known to this
process (some registered version exists in `plugins.registry`) — this API
never loads new code, the same boundary every other Admin API in this
codebase draws.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import (
    get_db_engine,
    get_population_policy_binding_repository,
    get_system_repository,
)
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.plugins import registry
from gov_platform.schemas.population_policy_binding import PopulationPolicyBindingLifecycleState

router = APIRouter(tags=["admin"])


class PopulationPolicyBindingRequest(BaseModel):
    system_id: str
    population_policy_id: str


class PopulationPolicyBindingResponse(BaseModel):
    id: str
    system_id: str
    population_policy_id: str
    lifecycle_state: PopulationPolicyBindingLifecycleState
    created_at: datetime


def _population_policy_id_known_to_this_process(population_policy_id: str) -> bool:
    return any(
        known_id == population_policy_id
        for known_id, _version in registry.known_population_policy_keys()
    )


@router.post(
    "/population-policy-bindings",
    response_model=PopulationPolicyBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_population_policy_binding(
    payload: PopulationPolicyBindingRequest,
    engine: Engine = Depends(get_db_engine),
    system_repository: SystemRepository = Depends(get_system_repository),
    population_policy_binding_repository: PopulationPolicyBindingRepository = Depends(
        get_population_policy_binding_repository
    ),
) -> PopulationPolicyBindingResponse:
    if not _population_policy_id_known_to_this_process(payload.population_policy_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "no POPULATION_POLICY implementation registered in this process for "
                f"population_policy_id={payload.population_policy_id!r}"
            ),
        )

    with Session(engine) as session:
        if system_repository.get(session, payload.system_id) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"no system with id {payload.system_id!r}",
            )
        existing = population_policy_binding_repository.get_by_identity(
            session,
            system_id=payload.system_id,
            population_policy_id=payload.population_policy_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"a population policy binding for system {payload.system_id!r} -> "
                    f"population policy {payload.population_policy_id!r} already exists"
                ),
            )
        binding = population_policy_binding_repository.create(
            session,
            system_id=payload.system_id,
            population_policy_id=payload.population_policy_id,
        )
        session.commit()

    return PopulationPolicyBindingResponse(**binding.model_dump())


@router.get(
    "/population-policy-bindings", response_model=list[PopulationPolicyBindingResponse]
)
def list_population_policy_bindings(
    engine: Engine = Depends(get_db_engine),
    population_policy_binding_repository: PopulationPolicyBindingRepository = Depends(
        get_population_policy_binding_repository
    ),
) -> list[PopulationPolicyBindingResponse]:
    with Session(engine) as session:
        bindings = population_policy_binding_repository.list_all(session)
    return [PopulationPolicyBindingResponse(**b.model_dump()) for b in bindings]


@router.get(
    "/population-policy-bindings/{binding_id}", response_model=PopulationPolicyBindingResponse
)
def get_population_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    population_policy_binding_repository: PopulationPolicyBindingRepository = Depends(
        get_population_policy_binding_repository
    ),
) -> PopulationPolicyBindingResponse:
    with Session(engine) as session:
        binding = population_policy_binding_repository.get(session, binding_id)

    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="population policy binding not found"
        )
    return PopulationPolicyBindingResponse(**binding.model_dump())


@router.post(
    "/population-policy-bindings/{binding_id}/activate",
    response_model=PopulationPolicyBindingResponse,
)
def activate_population_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    population_policy_binding_repository: PopulationPolicyBindingRepository = Depends(
        get_population_policy_binding_repository
    ),
) -> PopulationPolicyBindingResponse:
    with Session(engine) as session:
        if population_policy_binding_repository.get(session, binding_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="population policy binding not found",
            )
        binding = population_policy_binding_repository.set_lifecycle_state(
            session, binding_id, PopulationPolicyBindingLifecycleState.ACTIVE
        )
        session.commit()

    return PopulationPolicyBindingResponse(**binding.model_dump())


@router.post(
    "/population-policy-bindings/{binding_id}/deactivate",
    response_model=PopulationPolicyBindingResponse,
)
def deactivate_population_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    population_policy_binding_repository: PopulationPolicyBindingRepository = Depends(
        get_population_policy_binding_repository
    ),
) -> PopulationPolicyBindingResponse:
    """Deactivating a binding means the next `run_policies` invocation
    simply skips this (system, population policy) pair -- there is no
    in-flight request to fail closed on the way
    `policy_bindings/{id}/deactivate` does for ingestion (see that
    endpoint's docstring); population evaluation is already decoupled
    from any request/response cycle."""
    with Session(engine) as session:
        if population_policy_binding_repository.get(session, binding_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="population policy binding not found",
            )
        binding = population_policy_binding_repository.set_lifecycle_state(
            session, binding_id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

    return PopulationPolicyBindingResponse(**binding.model_dump())
