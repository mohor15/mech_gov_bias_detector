"""Canonical `Principal` -- architecture (no numbered section; see
`docs/milestones/M13.md` Sourcing note), M13 (Authentication &
Authorization).

A registered caller (human or machine) with a name, a role, and one
opaque bearer credential. The credential itself is deliberately never a
field on this model -- `Principal` is what a request handler receives
*after* successful authentication (`api/dependencies.get_current_principal`),
never what proves it. See `access/tokens.py` (the pure token/hash
mechanism) and `db/repositories/principal.py` (the only place the
plaintext token is ever available, and only once, at creation time).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrincipalRole(StrEnum):
    """Four roles, matching this platform's own real, observed caller
    shapes (`docs/milestones/M13.md` §4.1) -- not a general permission
    matrix (see §12.4/§13.4). `StrEnum`, not `(str, Enum)` -- matches
    `VerdictStatus`/`FindingOutcome`/`PluginType`'s own existing
    convention.
    """

    INGESTION = "INGESTION"  # POST to either ingestion route
    REVIEWER = "REVIEWER"  # claim/release/resolve on either review workflow
    ADMIN = "ADMIN"  # every mutating Admin API endpoint, plus everything REVIEWER/READ_ONLY can do
    READ_ONLY = "READ_ONLY"  # every read-only Admin API endpoint and the dashboard


class Principal(BaseModel):
    """A registered caller. The token itself is never a field here -- see
    `access/tokens.py` and `db/repositories/principal.py`."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    role: PrincipalRole
    created_at: datetime
    revoked_at: datetime | None = None
