"""Canonical Population Policy Binding — architecture §7/§8, M6.

Which `PopulationPolicy` evaluates which `System`'s decisions —
`system_id`-keyed, not `adapter_id`-keyed like `PolicyBinding`
(`schemas/policy_binding.py`, M5). A population-level analysis is
naturally about a System's aggregate decisions across however many
adapter versions have produced them over time, not about one adapter's
events — see `docs/milestones/M6.md` §13.8 for the full reasoning behind
this being a real, separate key decision, not a copy-paste of
`PolicyBinding`'s shape.

`parameters` (M8, architecture §10) is this binding's admin-configured
overrides (e.g. `threshold`, `minimum_group_size`, `z_critical`) for
whichever `PopulationPolicy` it names — empty by default, meaning "use
that policy's own built-in defaults." Set only at creation time; there is
no update-in-place endpoint, mirroring `PolicyBinding.severity`'s own
design intent (M5) — changing parameters means deactivating this binding
and creating a new one, now actually possible end to end since migration
`0022` relaxed this table's uniqueness to a partial index scoped to
`ACTIVE`. See `docs/milestones/M8.md` §4.4/§4.7/§13.19/§13.21.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PopulationPolicyBindingLifecycleState(StrEnum):
    """Whether this binding currently applies.

    Mirrors `PolicyBindingLifecycleState` — `ACTIVE`/`INACTIVE`, not a
    reuse of `plugin_registrations`' `DRAFT`/`SHADOW`/`PRODUCTION`: a
    binding answers "does this already-trusted population policy apply to
    this system", an orthogonal question to "is this population policy's
    code trusted to run at all", which `plugin_registrations` already
    fully owns (see `docs/milestones/M5.md` §13.2, applied identically
    here).
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PopulationPolicyBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    system_id: str = Field(..., min_length=1)
    population_policy_id: str = Field(..., min_length=1)
    lifecycle_state: PopulationPolicyBindingLifecycleState
    created_at: datetime
    parameters: dict[str, float] = Field(default_factory=dict)
