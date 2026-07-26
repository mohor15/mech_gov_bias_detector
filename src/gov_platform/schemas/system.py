"""Canonical System — architecture §16.1, formalized in M1.

Represents one connected source system (an LLM copilot, classical ML model,
rule engine, or hybrid) that the platform observes. M0's `DecisionEvent`
carried only a bare `system_id` string; M1 gives that string a real home —
a registered `System` row a `DecisionEvent` can be linked to.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class System(BaseModel):
    """A registered source system. `name` is the natural key referenced by
    `DecisionEvent.system_id` and by adapter wire-format `system_id` fields.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    domain: str | None = None
    risk_tier: str | None = None
    owner: str | None = None
    created_at: datetime
