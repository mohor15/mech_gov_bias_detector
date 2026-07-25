"""Canonical Decision Event — architecture §4.2.

M0 ships the minimal viable field set needed to prove the ingestion seam.
Two things are explicitly deferred, not forgotten:

* ``protected_attribute_refs`` currently carries raw string values as
  supplied by the adapter. Resolving them to direct / proxied / withheld
  per the Protected Attribute Resolution Service is M2 scope (architecture
  §4.3) — until then this field is a pass-through, not a governed one.
* System/ModelVersion identity is a bare ``system_id`` string. Formalizing
  it as a foreign key into a real System/ModelVersion registry is M1.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionEvent(BaseModel):
    """A single decision made by an external system, observed by the platform.

    Immutable once constructed: nothing downstream may mutate a
    `DecisionEvent` in place. `NormalizationService.normalize` returns a new
    instance rather than editing one, preserving the evidentiary integrity a
    governance platform depends on (architecture §4, P4/P9).
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., min_length=1)
    system_id: str = Field(..., min_length=1)
    decision_type: str = Field(..., min_length=1)
    subject_ref: str = Field(..., min_length=1, description="Pseudonymous reference to the subject")

    occurred_at: datetime = Field(..., description="When the source system made the decision.")
    ingested_at: datetime = Field(..., description="When the platform received it.")

    input_features: dict[str, float] = Field(default_factory=dict)
    protected_attribute_refs: dict[str, str] = Field(default_factory=dict)
    decision_output: dict[str, object] = Field(default_factory=dict)

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value
