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

M8 (architecture §10): the request/response bodies gain an optional
`parameters` field (admin-configured overrides for whichever policy this
binding names). The conflict pre-check now calls
`get_active_by_identity`, not `get_by_identity` — a deactivated binding
no longer blocks creating a new one for the same
`(system_id, population_policy_id)` pair, which migration `0022`'s
partial unique index now permits at the database level too. Using
`get_by_identity` here would still be lifecycle-blind and would silently
defeat the whole point of the schema change; see
`docs/milestones/M8.md` §4.4/§13.19.

`_reject_non_finite_parameters` (post-freeze addendum): rejects a
`NaN`/`Infinity` parameter value with a `422`, rather than accepting and
persisting it (found and confirmed during this milestone's own
hostile-review pass, then explicitly raised by the user for a decision —
see `docs/milestones/M8.md`'s Production-Readiness Review addendum). This
is deliberately **not** the per-metric semantic validation (`threshold`
must be in `(0, 1]`, `z_critical` must be `> 0`) the design explicitly
kept out of the API layer (§4.7/§13.2) — no policy's specific valid range
is referenced here. "Is this a finite number at all" is a universal
precondition true for *every* population policy's *every* parameter, not
a per-metric judgment call the API would need to know about; each
policy's own `_resolve_parameters` still separately validates its own
range and stays the authority on what's semantically sane for it,
unchanged.

Implemented as an explicit `HTTPException` check in the endpoint body,
mirroring every other validation check in this file (unknown system,
unknown `population_policy_id`, conflict) — **not** a Pydantic
`field_validator`, which was tried first and found to have a real,
empirically-confirmed problem: raising `ValueError` from a validator
still passes Pydantic/FastAPI's own request-validation machinery, which
echoes the raw invalid (`NaN`) value back inside its structured error
detail; Starlette's `JSONResponse` renderer disallows `NaN`
(`allow_nan=False`) and raises trying to serialize *that* echoed value
while building the very error response meant to reject it, producing a
confusing, generic `"Out of range float values are not JSON compliant"`
message instead of a clear one. An explicit `HTTPException` with a plain
string `detail` we construct ourselves never echoes the raw float back at
all, sidestepping the problem entirely.
"""

from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import (
    get_db_engine,
    get_population_policy_binding_repository,
    get_system_repository,
    require_role,
)
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.plugins import registry
from gov_platform.schemas.population_policy_binding import PopulationPolicyBindingLifecycleState
from gov_platform.schemas.principal import PrincipalRole

router = APIRouter(tags=["admin"])


class PopulationPolicyBindingRequest(BaseModel):
    system_id: str
    population_policy_id: str
    parameters: dict[str, float] | None = None


def _reject_non_finite_parameters(parameters: dict[str, float] | None) -> None:
    """`NaN`/`Infinity` are technically valid Python/IEEE-754 floats but
    never a meaningful value for any population-policy parameter -- a
    universal well-formedness precondition, not a per-metric semantic
    judgment (contrast `threshold`'s `(0, 1]` range, which stays validated
    inside `adverse_impact_ratio.py` itself, per §4.7/§13.2's explicit
    choice to keep the API layer ignorant of that). Raises a plain
    `HTTPException` with a string `detail` we build ourselves -- never
    echoing the raw invalid float back in a structured error payload,
    which is what broke when this was first tried as a Pydantic
    `field_validator` (see this module's docstring)."""
    if parameters is None:
        return
    for key, number in parameters.items():
        if not math.isfinite(number):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"parameters[{key!r}] must be a finite number -- "
                    "NaN and +/-Infinity are never valid for any population-policy parameter"
                ),
            )


class PopulationPolicyBindingResponse(BaseModel):
    id: str
    system_id: str
    population_policy_id: str
    lifecycle_state: PopulationPolicyBindingLifecycleState
    created_at: datetime
    parameters: dict[str, float] = Field(default_factory=dict)


def _population_policy_id_known_to_this_process(population_policy_id: str) -> bool:
    return any(
        known_id == population_policy_id
        for known_id, _version in registry.known_population_policy_keys()
    )


@router.post(
    "/population-policy-bindings",
    response_model=PopulationPolicyBindingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
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
    _reject_non_finite_parameters(payload.parameters)

    with Session(engine) as session:
        if system_repository.get(session, payload.system_id) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"no system with id {payload.system_id!r}",
            )
        existing = population_policy_binding_repository.get_active_by_identity(
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
            parameters=payload.parameters,
        )
        session.commit()

    return PopulationPolicyBindingResponse(**binding.model_dump())


@router.get(
    "/population-policy-bindings",
    response_model=list[PopulationPolicyBindingResponse],
    dependencies=[Depends(require_role(*PrincipalRole))],
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
    "/population-policy-bindings/{binding_id}",
    response_model=PopulationPolicyBindingResponse,
    dependencies=[Depends(require_role(*PrincipalRole))],
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
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
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
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
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
