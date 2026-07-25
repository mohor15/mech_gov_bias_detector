"""Canonical Finding — the output of a single Policy evaluating a single
Decision Event (architecture §7)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FindingOutcome(StrEnum):
    """A policy's raw verdict on one Decision Event.

    Kept binary in M0 because the only policy that exists is the reference
    always-ALLOW policy. Real policies (rule-based gates, counterfactual
    fairness, statistical/population tests) arrive from M2 onward and will
    populate ``metric_values``/``rationale`` meaningfully — the outcome
    vocabulary itself does not need to grow to support them.
    """

    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class Finding(BaseModel):
    """One policy's evaluation of one Decision Event."""

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(..., min_length=1)
    decision_event_id: str = Field(..., min_length=1)
    policy_id: str = Field(..., min_length=1)
    policy_version: str = Field(..., min_length=1)

    outcome: FindingOutcome
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=1)
    metric_values: dict[str, float] = Field(default_factory=dict)

    evaluated_at: datetime
