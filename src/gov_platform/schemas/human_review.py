"""Human Review Workflow — architecture §12, M9.

A `VerdictReview` tracks the review lifecycle of one `GovernanceVerdict`
whose `status` is `ESCALATE_FOR_REVIEW` or `RECOMMEND_HOLD` (M5); a
`PopulationFindingReview` tracks the identical lifecycle for one
`PopulationFinding` whose `outcome` is `FLAGGED` (M6/M8). Two structurally
separate types, mirroring `Verdict`/`PopulationFinding` themselves being
two structurally separate types (`docs/milestones/M6.md` §13.3) — a review
of one is not interchangeable with a review of the other, so this module
defines two full parallel shapes rather than one polymorphic type. See
`docs/milestones/M9.md` §3.2 for the full reasoning, including why each
gets its own small `...Status`/`...Resolution` enum pair rather than a
shared one (mirroring `PolicyBindingLifecycleState`/
`PopulationPolicyBindingLifecycleState`'s own precedent for exactly this
duplication, §3.3).

Both review types are ordinary, unsigned, mutable workflow state — not
evidentiary records. `VerdictReview`/`PopulationFindingReview` reference
their subject by id only (`verdict_id`/`population_finding_id`); the
subject itself (`GovernanceVerdict`/`PopulationFinding`) remains exactly as
signed/chained/immutable as before M9 (`docs/milestones/M9.md` §3.1).

`_REVIEWABLE_VERDICT_STATUSES` is the one canonical definition of "which
`VerdictStatus` values create a review" — both the live write path
(`audit/evidence_store.py`) and the reconciliation tool
(`human_review/backfill_reviews.py`) import this same constant rather than
each keeping an independent copy that could silently drift out of sync
(`docs/milestones/M9.md` §5.1/§7). `ALLOW`/`ALLOW_WITH_FLAG` are excluded
(no review is ever warranted for either); the legacy pre-M5
`VerdictStatus.FLAGGED` is excluded too — no live code path can ever
produce it, and no `PolicySeverity` was ever computed for a verdict written
under that older model (`docs/milestones/M9.md` §3.6/§9.4).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from gov_platform.schemas.verdict import VerdictStatus


class VerdictReviewStatus(StrEnum):
    """A `VerdictReview`'s own workflow state — orthogonal to
    `VerdictStatus` (what `GovernanceEngine` computed) and to
    `PolicyBindingLifecycleState`/`PopulationPolicyBindingLifecycleState`
    (whether a binding currently applies). `OPEN` → `IN_REVIEW` →
    `RESOLVED`, with an explicit `IN_REVIEW` → `OPEN` release transition
    for an abandoned claim (`docs/milestones/M9.md` §3.3)."""

    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


class VerdictReviewResolution(StrEnum):
    """A reviewer's final judgment on one `VerdictReview`, set only when
    `status` becomes `RESOLVED`. Kept binary, mirroring `FindingOutcome`/
    `PopulationFindingOutcome`'s own "binary until a third value earns its
    way in" discipline — see `docs/milestones/M9.md` §3.3."""

    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class VerdictReview(BaseModel):
    """One review record for one `GovernanceVerdict`. `RESOLVED` is
    terminal *for this row*, not for the `Verdict` it references — a
    resolved review can be superseded by a new row (never a mutation of
    this one) once a later need to re-examine the same verdict arises,
    via the partial unique index `one_open_verdict_review_per_verdict`
    (at most one *active*, i.e. non-`RESOLVED`, review per verdict at a
    time) — see `docs/milestones/M9.md` §3.2."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    verdict_id: str = Field(..., min_length=1)
    status: VerdictReviewStatus
    reviewer: str | None = Field(default=None, min_length=1)
    resolution: VerdictReviewResolution | None = None
    resolution_notes: str | None = Field(default=None, min_length=1)
    created_at: datetime
    claimed_at: datetime | None = None
    resolved_at: datetime | None = None


class PopulationFindingReviewStatus(StrEnum):
    """Mirrors `VerdictReviewStatus` exactly — kept as a separate enum
    (not a shared one) so each can evolve independently, the same
    reasoning `PolicyBindingLifecycleState`/
    `PopulationPolicyBindingLifecycleState` already established for their
    own identical-valued pair (`docs/milestones/M9.md` §3.3)."""

    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


class PopulationFindingReviewResolution(StrEnum):
    """Mirrors `VerdictReviewResolution` — a separate enum, not a shared
    one, for the same reason."""

    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class PopulationFindingReview(BaseModel):
    """One review record for one `PopulationFinding`. Mirrors
    `VerdictReview`'s shape exactly, referencing `population_finding_id`
    instead of `verdict_id` — see that class's docstring for the
    reopening/terminality reasoning, identical here."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    population_finding_id: str = Field(..., min_length=1)
    status: PopulationFindingReviewStatus
    reviewer: str | None = Field(default=None, min_length=1)
    resolution: PopulationFindingReviewResolution | None = None
    resolution_notes: str | None = Field(default=None, min_length=1)
    created_at: datetime
    claimed_at: datetime | None = None
    resolved_at: datetime | None = None


_REVIEWABLE_VERDICT_STATUSES: frozenset[VerdictStatus] = frozenset(
    {VerdictStatus.ESCALATE_FOR_REVIEW, VerdictStatus.RECOMMEND_HOLD}
)
