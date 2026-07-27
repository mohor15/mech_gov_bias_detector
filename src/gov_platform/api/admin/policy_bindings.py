"""Policy Bindings Admin API — architecture §7/§8, M5.

Manages which policy families govern which adapters — a database fact,
changeable without a redeploy (see `schemas/policy_binding.py` and
`docs/milestones/M5.md`). Mirrors `api/admin/plugins.py`'s shape: `POST` to
create, `GET` to list/read, explicit named actions
(`activate`/`deactivate`) rather than a general `PATCH`, the same
auditability reasoning M3's `promote` endpoint already established.

Both `adapter_id` and `policy_id` must already be known to this process
(some registered version exists in `plugins.registry`) — this API changes
which already-deployed policy governs which already-deployed adapter; it
never loads new code, the same boundary `api/admin/plugins.py` draws.

Handlers are plain `def`, not `async def` — same reasoning as every other
route in this codebase.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import get_db_engine, get_policy_binding_repository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.plugins import registry
from gov_platform.schemas.policy_binding import PolicyBindingLifecycleState, PolicySeverity

router = APIRouter(tags=["admin"])


class PolicyBindingRequest(BaseModel):
    adapter_id: str
    policy_id: str
    severity: PolicySeverity


class PolicyBindingResponse(BaseModel):
    id: str
    adapter_id: str
    policy_id: str
    severity: PolicySeverity
    lifecycle_state: PolicyBindingLifecycleState
    created_at: datetime


def _adapter_id_known_to_this_process(adapter_id: str) -> bool:
    return any(known_id == adapter_id for known_id, _version in registry.known_adapter_keys())


def _policy_id_known_to_this_process(policy_id: str) -> bool:
    return any(known_id == policy_id for known_id, _version in registry.known_policy_keys())


@router.post(
    "/policy-bindings", response_model=PolicyBindingResponse, status_code=status.HTTP_201_CREATED
)
def create_policy_binding(
    payload: PolicyBindingRequest,
    engine: Engine = Depends(get_db_engine),
    policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
) -> PolicyBindingResponse:
    if not _adapter_id_known_to_this_process(payload.adapter_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"no ADAPTER implementation registered in this process for "
                f"adapter_id={payload.adapter_id!r}"
            ),
        )
    if not _policy_id_known_to_this_process(payload.policy_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"no POLICY implementation registered in this process for "
                f"policy_id={payload.policy_id!r}"
            ),
        )

    with Session(engine) as session:
        existing = policy_binding_repository.get_by_identity(
            session, adapter_id=payload.adapter_id, policy_id=payload.policy_id
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"a policy binding for adapter {payload.adapter_id!r} -> policy "
                    f"{payload.policy_id!r} already exists"
                ),
            )
        binding = policy_binding_repository.create(
            session,
            adapter_id=payload.adapter_id,
            policy_id=payload.policy_id,
            severity=payload.severity,
        )
        session.commit()

    return PolicyBindingResponse(**binding.model_dump())


@router.get("/policy-bindings", response_model=list[PolicyBindingResponse])
def list_policy_bindings(
    engine: Engine = Depends(get_db_engine),
    policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
) -> list[PolicyBindingResponse]:
    with Session(engine) as session:
        bindings = policy_binding_repository.list_all(session)
    return [PolicyBindingResponse(**b.model_dump()) for b in bindings]


@router.get("/policy-bindings/{binding_id}", response_model=PolicyBindingResponse)
def get_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
) -> PolicyBindingResponse:
    with Session(engine) as session:
        binding = policy_binding_repository.get(session, binding_id)

    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="policy binding not found"
        )
    return PolicyBindingResponse(**binding.model_dump())


@router.post("/policy-bindings/{binding_id}/activate", response_model=PolicyBindingResponse)
def activate_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
) -> PolicyBindingResponse:
    with Session(engine) as session:
        if policy_binding_repository.get(session, binding_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="policy binding not found"
            )
        binding = policy_binding_repository.set_lifecycle_state(
            session, binding_id, PolicyBindingLifecycleState.ACTIVE
        )
        session.commit()

    return PolicyBindingResponse(**binding.model_dump())


@router.post("/policy-bindings/{binding_id}/deactivate", response_model=PolicyBindingResponse)
def deactivate_policy_binding(
    binding_id: str,
    engine: Engine = Depends(get_db_engine),
    policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
) -> PolicyBindingResponse:
    """Deactivating every active binding for an adapter means the next
    ingestion request for it gets a clean 503 (`api/ingestion/routes.py`'s
    "no active policy bindings" check) — the same "fail closed, not open"
    posture M3 already established for a demoted/never-registered policy."""
    with Session(engine) as session:
        if policy_binding_repository.get(session, binding_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="policy binding not found"
            )
        binding = policy_binding_repository.set_lifecycle_state(
            session, binding_id, PolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

    return PolicyBindingResponse(**binding.model_dump())
