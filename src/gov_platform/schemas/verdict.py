"""Canonical Governance Verdict — architecture §8.2.

``VerdictStatus`` here is a deliberately minimal two-value placeholder
(ALLOW / FLAGGED), not the architecture's full four-state model
(ALLOW / ALLOW_WITH_FLAG / ESCALATE_FOR_REVIEW / RECOMMEND_HOLD). The full
state machine only means something once Policy Bindings, escalation rules,
and signing exist to drive it — that is M5's job. Building the four-value
enum now, unused, would be scope creep ahead of the milestone that gives it
meaning.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from gov_platform.schemas.finding import Finding


class VerdictStatus(StrEnum):
    ALLOW = "ALLOW"
    FLAGGED = "FLAGGED"


class GovernanceVerdict(BaseModel):
    """The Governance Engine's output: one or more Findings, aggregated.

    ``findings`` is plural because that is what a Verdict *is* per the
    architecture — M0 through M3's `GovernanceEngine` only ever ran one
    `Policy`, so this list only ever had length 1 until M4, which is when
    real multi-policy aggregation and disagreement handling arrived (an
    adapter with more than one governing policy now produces a Verdict
    with more than one Finding here).
    """

    model_config = ConfigDict(frozen=True)

    verdict_id: str = Field(..., min_length=1)
    decision_event_id: str = Field(..., min_length=1)
    status: VerdictStatus
    findings: list[Finding] = Field(..., min_length=1)
    created_at: datetime
