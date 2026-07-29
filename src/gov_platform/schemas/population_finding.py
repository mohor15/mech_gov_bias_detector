"""Canonical Population Finding — architecture §7/§13, M6.

The output of one `PopulationPolicy` evaluating one `PopulationWindow`
(`population_engine/base.py`) — deliberately not a reuse of `Finding`
(`schemas/finding.py`): `Finding.decision_event_id` is a hard,
load-bearing single-event key that a population-level result cannot
honestly satisfy (there is no one `DecisionEvent` a "30% of this group's
approvals fall below the reference rate" result belongs to). See
`docs/milestones/M6.md` §13.3/§9 for the full reasoning behind a new,
parallel type instead of widening `Finding`.

`classification_snapshot` is the hostile-review-pass fix for historical
reproducibility (`docs/milestones/M6.md` §13.16): `protected_attribute_rules`
(M5) is live, admin-mutable data with no versioning of its own, unlike
`population_policy_version`, which already pins the policy's *code*
identity. A finding embeds exactly which `(attribute_name -> classification)`
pairs it was computed against, rather than pointing at a table that can
keep changing underneath it — the same reason `evidence_chain.payload`
embeds the full `decision_event`/`verdict` rather than just their ids.
This field is part of what gets signed (see `audit/verify_population_findings.py`),
not just informational metadata.

This model deliberately carries no `signature`/`signing_key_id` — those are
a persistence-layer concern, added by `db/repositories/population_finding.py`'s
`PopulationFindingRecord`, the same split `audit/evidence_store.py` draws
between `GovernanceVerdict` (no signature) and `EvidenceRecord` (has one).

`parameters_used` (M8, architecture §10) is the reproducibility fix for
admin-configurable population-policy parameters, the exact same discipline
`classification_snapshot` established for `protected_attribute_rules`:
the *effective* parameter values (defaults included, not only overrides)
a policy actually used, immune to a later change to its binding.
Deliberately `dict[str, float] | None`, not `Field(default_factory=dict)`
— every `PopulationFinding` signed before this field existed must
continue to hash and verify identically to how it was originally signed,
which `None` (excluded from the signed payload by
`audit/verify_population_findings.py`'s `exclude_none=True`) preserves and
an always-present `{}` would not. See `docs/milestones/M8.md` §4.5/§13.18
for the full reasoning — this is the first time this codebase has added a
field to an already-populated signed model, a genuinely different problem
than adding one before any record exists under the older shape (which is
how `classification_snapshot` itself was added, at M6, before any
`PopulationFinding` had ever been signed at all).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PopulationFindingOutcome(StrEnum):
    """A population policy's raw verdict on one window.

    Kept binary, mirroring `FindingOutcome` — see
    `docs/milestones/M6.md` §13.10: population findings carry no
    severity/escalation state this milestone (there is still no Human
    Review Workflow, M9, for *any* escalated output to go to), so there is
    nothing for a third value to encode yet.
    """

    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class PopulationFinding(BaseModel):
    """One `PopulationPolicy`'s evaluation of one `PopulationWindow`."""

    model_config = ConfigDict(frozen=True)

    population_finding_id: str = Field(..., min_length=1)
    population_policy_id: str = Field(..., min_length=1)
    population_policy_version: str = Field(..., min_length=1)
    system_id: str = Field(..., min_length=1)

    window_start: datetime
    window_end: datetime

    outcome: PopulationFindingOutcome
    metric_values: dict[str, float] = Field(default_factory=dict)
    classification_snapshot: dict[str, str] = Field(default_factory=dict)
    parameters_used: dict[str, float] | None = None
    rationale: str = Field(..., min_length=1)

    evaluated_at: datetime
