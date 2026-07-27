"""Canonical Governance Verdict — architecture §8.2.

``VerdictStatus`` is the full four-state model as of M5
(ALLOW / ALLOW_WITH_FLAG / ESCALATE_FOR_REVIEW / RECOMMEND_HOLD), computed
by `GovernanceEngine` from the highest `PolicySeverity` among a verdict's
flagged findings — see `governance_engine/engine.py`.

``FLAGGED`` is kept as a permanent, historical-only member, not removed.
M0 through M4 persisted real `Verdict` rows with `status="FLAGGED"`, embedded
in the hash-chained `evidence_chain.payload` JSON blob at write time — that
table has `UPDATE`/`DELETE` revoked at the database-privilege level
(migration `0008`), so those historical records can never legitimately
change. Removing `FLAGGED` from this enum would make `VerdictStatus(row.status)`
raise for every pre-M5 row on read. No M5+ code path ever *constructs* a new
`GovernanceVerdict` with `FLAGGED` — see `docs/milestones/M5.md` §13.10.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from gov_platform.schemas.finding import Finding


class VerdictStatus(StrEnum):
    ALLOW = "ALLOW"
    ALLOW_WITH_FLAG = "ALLOW_WITH_FLAG"
    ESCALATE_FOR_REVIEW = "ESCALATE_FOR_REVIEW"
    RECOMMEND_HOLD = "RECOMMEND_HOLD"

    # Legacy, pre-M5 value. Historical reads only -- see this module's
    # docstring. Never constructed by M5+ code.
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
