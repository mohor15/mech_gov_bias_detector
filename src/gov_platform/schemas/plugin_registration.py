"""Canonical Plugin Registration — architecture §6, M3.

A `PluginRegistration` records the operational, DB-backed fact of *which*
already-deployed `Adapter`/`Policy` implementation is currently trusted to
run, and at what lifecycle stage — separate from the in-process
`plugins.registry`, which records *what implementations this process's
own code knows how to run at all*. See `plugins/registry.py`'s module
docstring for the full split.

M6: `PluginType` gains `POPULATION_POLICY` — a `PopulationPolicy`
(`population_engine/base.py`) registers, promotes, and is looked up
through this exact same table and lifecycle mechanism every `Adapter`/
`Policy` already uses. See `docs/milestones/M6.md` §13.7: no second
lifecycle mechanism was invented for the third plugin kind.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PluginType(StrEnum):
    ADAPTER = "ADAPTER"
    POLICY = "POLICY"
    POPULATION_POLICY = "POPULATION_POLICY"


class PluginLifecycleState(StrEnum):
    """A plugin's promotion stage.

    ``DRAFT``: registered, not yet live — an adapter's ingestion route
    rejects real traffic; a policy never runs against real events.
    ``SHADOW``: runs against real traffic. For a policy, its `Finding` is
    recorded for comparison but never influences the served `Verdict`
    (see `docs/milestones/M3.md` §13.3 — this is deliberately not M4's
    policy plurality). For an adapter, M3 does not yet give `SHADOW` a
    distinct meaning from `PRODUCTION` — both fully process and persist
    real traffic; see that same doc's production-readiness review.
    ``PRODUCTION``: fully live. At most one `PRODUCTION` registration may
    exist per `(plugin_type, plugin_id)` at a time — enforced by a
    database constraint, not application code alone.
    """

    DRAFT = "DRAFT"
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"


class PluginRegistration(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    plugin_type: PluginType
    plugin_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    lifecycle_state: PluginLifecycleState
    registered_at: datetime
    promoted_at: datetime | None = None
