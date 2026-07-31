"""Session endpoints for the M10 dashboard — architecture (no numbered
section; see `docs/milestones/M13.md` Sourcing note), M13.

Exchanges a bearer token (already issued by `access/create_principal.py`)
for an `HttpOnly` session cookie, so a browser doesn't have to attach an
`Authorization` header to every page load -- the one, minimal HTTP
surface this milestone adds beyond gating every existing endpoint (see
`docs/milestones/M13.md` §5.5/§7). Reuses the identical principal/token
mechanism every other caller already uses -- not a second, parallel auth
system.

Handlers are plain `def`, not `async def` -- same reasoning as every
other route in this codebase.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import (
    AuthenticationError,
    get_db_engine,
    get_principal_repository,
    resolve_principal_from_token,
)
from gov_platform.db.repositories.principal import PrincipalRepository

router = APIRouter(tags=["auth"])

# Matches api/dependencies._extract_token's own cookie name.
_SESSION_COOKIE_NAME = "gov_platform_session"


class CreateSessionRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def create_session(
    payload: CreateSessionRequest,
    response: Response,
    engine: Engine = Depends(get_db_engine),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
) -> None:
    """Validates `payload.token` exactly the way `get_current_principal`
    validates a header/cookie-sourced one (`resolve_principal_from_token`),
    and on success sets an `HttpOnly`, `Secure`, `SameSite=Strict` cookie
    carrying that same token -- `get_current_principal`'s existing
    hash-and-look-up logic needs no cookie-specific branch beyond reading
    from a different request location."""
    with Session(engine) as session:
        principal = resolve_principal_from_token(session, principal_repository, payload.token)
    if principal is None:
        raise AuthenticationError("invalid or revoked credential")
    response.set_cookie(
        _SESSION_COOKIE_NAME,
        payload.token,
        httponly=True,
        secure=True,
        samesite="strict",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    """Clears the session cookie. Does **not** revoke the underlying
    principal's token (it may still be valid for non-browser use) --
    logging out of the dashboard and revoking API access are different
    actions; conflating them would surprise an operator who also uses the
    same token from a script (`docs/milestones/M13.md` §5.5)."""
    response.delete_cookie(_SESSION_COOKIE_NAME)
