"""Canonical Policy Binding — architecture §7/§8, M5.

Dynamic, admin-managed replacement for the static, code-defined
`Adapter.governing_policy_ids` tuple M3/M4 built: which policy families
govern an adapter's events is now a database fact, changeable without a
redeploy. Keyed by `adapter_id`, not `System.domain`/jurisdiction — see
`docs/milestones/M5.md` §13.1 for why the richer, domain/jurisdiction-keyed
design is deferred until a second real domain exists to validate it against.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PolicySeverity(StrEnum):
    """How serious a `FLAGGED` finding from this binding's policy is, in
    the context of this specific adapter — an administrative judgment, not
    a property of the policy's own code (see `docs/milestones/M5.md` §13.5
    for why this lives here and not on `Policy`). Drives which non-`ALLOW`
    `VerdictStatus` a flagged verdict lands in — see
    `governance_engine/engine.py`.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyBindingLifecycleState(StrEnum):
    """Whether this binding currently applies.

    Deliberately not a reuse of `plugin_registrations`' `DRAFT`/`SHADOW`/
    `PRODUCTION` — a binding answers "does this already-trusted policy
    apply here", an orthogonal question to "is this policy's code trusted
    to run at all", which the plugin registry already fully owns. See
    `docs/milestones/M5.md` §13.2.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PolicyBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    adapter_id: str = Field(..., min_length=1)
    policy_id: str = Field(..., min_length=1)
    severity: PolicySeverity
    lifecycle_state: PolicyBindingLifecycleState
    created_at: datetime
