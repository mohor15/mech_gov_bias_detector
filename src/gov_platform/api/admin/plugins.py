"""Plugin registry admin API — architecture §6, M3.

Manages *lifecycle state* only for plugins this process's own code
already knows how to run (see `plugins/registry.py`) — registering a
`plugin_id`/`version` this process has no matching `@register_adapter`/
`@register_policy` for is rejected, not silently accepted. This API
changes state for something that already self-registered at import time;
it never loads new code (`docs/milestones/M3.md` §13.5).

Handlers are plain `def`, not `async def` — same reasoning as every other
route in this codebase (see `api/ingestion/routes.py`'s docstring).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import (
    get_db_engine,
    get_plugin_registration_repository,
    require_role,
)
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.plugins import registry
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType
from gov_platform.schemas.principal import PrincipalRole

router = APIRouter(tags=["admin"])


class PluginRegistrationRequest(BaseModel):
    plugin_type: PluginType
    plugin_id: str
    version: str


class PluginRegistrationResponse(BaseModel):
    id: str
    plugin_type: PluginType
    plugin_id: str
    version: str
    lifecycle_state: PluginLifecycleState
    registered_at: datetime
    promoted_at: datetime | None


def _known_to_this_process(plugin_type: PluginType, plugin_id: str, version: str) -> bool:
    if plugin_type is PluginType.ADAPTER:
        return registry.get_adapter_class(plugin_id, version) is not None
    return registry.get_policy_class(plugin_id, version) is not None


@router.post(
    "/plugins",
    response_model=PluginRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
)
def register_plugin(
    payload: PluginRegistrationRequest,
    engine: Engine = Depends(get_db_engine),
    plugin_registration_repository: PluginRegistrationRepository = Depends(
        get_plugin_registration_repository
    ),
) -> PluginRegistrationResponse:
    if not _known_to_this_process(payload.plugin_type, payload.plugin_id, payload.version):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"no {payload.plugin_type.value} implementation registered in this "
                f"process for plugin_id={payload.plugin_id!r} version={payload.version!r} "
                "-- deploy the code and add it to plugins/bootstrap.py first"
            ),
        )

    with Session(engine) as session:
        existing = plugin_registration_repository.get_by_identity(
            session,
            plugin_type=payload.plugin_type,
            plugin_id=payload.plugin_id,
            version=payload.version,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{payload.plugin_type.value} {payload.plugin_id!r} version "
                    f"{payload.version!r} is already registered"
                ),
            )
        registration = plugin_registration_repository.create(
            session,
            plugin_type=payload.plugin_type,
            plugin_id=payload.plugin_id,
            version=payload.version,
        )
        session.commit()

    return PluginRegistrationResponse(**registration.model_dump())


@router.get(
    "/plugins",
    response_model=list[PluginRegistrationResponse],
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def list_plugins(
    engine: Engine = Depends(get_db_engine),
    plugin_registration_repository: PluginRegistrationRepository = Depends(
        get_plugin_registration_repository
    ),
) -> list[PluginRegistrationResponse]:
    with Session(engine) as session:
        registrations = plugin_registration_repository.list_all(session)
    return [PluginRegistrationResponse(**r.model_dump()) for r in registrations]


@router.get(
    "/plugins/{registration_id}",
    response_model=PluginRegistrationResponse,
    dependencies=[Depends(require_role(*PrincipalRole))],
)
def get_plugin(
    registration_id: str,
    engine: Engine = Depends(get_db_engine),
    plugin_registration_repository: PluginRegistrationRepository = Depends(
        get_plugin_registration_repository
    ),
) -> PluginRegistrationResponse:
    with Session(engine) as session:
        registration = plugin_registration_repository.get(session, registration_id)

    if registration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="plugin registration not found"
        )
    return PluginRegistrationResponse(**registration.model_dump())


@router.post(
    "/plugins/{registration_id}/promote",
    response_model=PluginRegistrationResponse,
    dependencies=[Depends(require_role(PrincipalRole.ADMIN))],
)
def promote_plugin(
    registration_id: str,
    engine: Engine = Depends(get_db_engine),
    plugin_registration_repository: PluginRegistrationRepository = Depends(
        get_plugin_registration_repository
    ),
) -> PluginRegistrationResponse:
    """Advance one lifecycle stage. 404 if the registration doesn't exist;
    a 422 (via `PluginRegistrationRepository.promote`'s `ValueError`, same
    mechanism M2 established) if it's already `PRODUCTION`. Promoting into
    `PRODUCTION` demotes whatever previously held that slot to `SHADOW` —
    see that repository's docstring."""
    with Session(engine) as session:
        if plugin_registration_repository.get(session, registration_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="plugin registration not found"
            )
        registration = plugin_registration_repository.promote(session, registration_id)
        session.commit()

    return PluginRegistrationResponse(**registration.model_dump())
