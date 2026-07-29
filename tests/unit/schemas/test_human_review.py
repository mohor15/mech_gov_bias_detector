from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.human_review import (
    _REVIEWABLE_VERDICT_STATUSES,
    PopulationFindingReview,
    PopulationFindingReviewResolution,
    PopulationFindingReviewStatus,
    VerdictReview,
    VerdictReviewResolution,
    VerdictReviewStatus,
)
from gov_platform.schemas.verdict import VerdictStatus


def _verdict_review(**overrides: object) -> VerdictReview:
    defaults: dict[str, object] = {
        "id": "review-001",
        "verdict_id": "verdict-001",
        "status": VerdictReviewStatus.OPEN,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return VerdictReview(**defaults)  # type: ignore[arg-type]


def _population_finding_review(**overrides: object) -> PopulationFindingReview:
    defaults: dict[str, object] = {
        "id": "review-001",
        "population_finding_id": "finding-001",
        "status": PopulationFindingReviewStatus.OPEN,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PopulationFindingReview(**defaults)  # type: ignore[arg-type]


def test_reviewable_verdict_statuses_includes_escalate_and_recommend_hold() -> None:
    """Approved final architecture (docs/milestones/M9.md §9.1/§10): both
    are reviewable, not only the architecture's literally-cited
    ESCALATE_FOR_REVIEW. A regression guard against someone later
    "simplifying" this to `status != ALLOW`, which would silently include
    ALLOW_WITH_FLAG too."""
    assert {
        VerdictStatus.ESCALATE_FOR_REVIEW,
        VerdictStatus.RECOMMEND_HOLD,
    } == _REVIEWABLE_VERDICT_STATUSES


def test_reviewable_verdict_statuses_excludes_allow_and_allow_with_flag() -> None:
    assert VerdictStatus.ALLOW not in _REVIEWABLE_VERDICT_STATUSES
    assert VerdictStatus.ALLOW_WITH_FLAG not in _REVIEWABLE_VERDICT_STATUSES


def test_reviewable_verdict_statuses_excludes_the_legacy_pre_m5_flagged_status() -> None:
    """docs/milestones/M9.md §3.6/§9.4: no live code path can ever produce
    this status after M5 shipped, and no PolicySeverity was ever computed
    for it."""
    assert VerdictStatus.FLAGGED not in _REVIEWABLE_VERDICT_STATUSES


def test_verdict_review_constructs_with_defaults() -> None:
    review = _verdict_review()
    assert review.status is VerdictReviewStatus.OPEN
    assert review.reviewer is None
    assert review.resolution is None
    assert review.resolution_notes is None
    assert review.claimed_at is None
    assert review.resolved_at is None


def test_verdict_review_is_frozen() -> None:
    review = _verdict_review()
    with pytest.raises(ValidationError):
        review.status = VerdictReviewStatus.RESOLVED  # type: ignore[misc]


def test_verdict_review_round_trips_a_resolved_state() -> None:
    review = _verdict_review(
        status=VerdictReviewStatus.RESOLVED,
        reviewer="jane",
        resolution=VerdictReviewResolution.CONFIRMED,
        resolution_notes="a real disparity, escalated to compliance",
        claimed_at=datetime(2026, 1, 1, tzinfo=UTC),
        resolved_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert review.resolution is VerdictReviewResolution.CONFIRMED
    assert review.resolution_notes == "a real disparity, escalated to compliance"


def test_verdict_review_rejects_an_empty_reviewer_string() -> None:
    with pytest.raises(ValidationError):
        _verdict_review(reviewer="")


def test_verdict_review_rejects_empty_resolution_notes() -> None:
    """Mirrors the mandatory, non-empty `rationale` this codebase already
    requires on every Finding/PopulationFinding -- a resolution with no
    stated reason is not a meaningfully different failure mode
    (docs/milestones/M9.md §3.3)."""
    with pytest.raises(ValidationError):
        _verdict_review(resolution_notes="")


def test_population_finding_review_constructs_with_defaults() -> None:
    review = _population_finding_review()
    assert review.status is PopulationFindingReviewStatus.OPEN
    assert review.reviewer is None
    assert review.resolution is None


def test_population_finding_review_is_frozen() -> None:
    review = _population_finding_review()
    with pytest.raises(ValidationError):
        review.status = PopulationFindingReviewStatus.RESOLVED  # type: ignore[misc]


def test_population_finding_review_rejects_empty_resolution_notes() -> None:
    with pytest.raises(ValidationError):
        _population_finding_review(resolution_notes="")


def test_population_finding_review_resolution_is_a_separate_enum_from_verdict_reviews() -> None:
    """docs/milestones/M9.md §3.3: two separate enums, not one shared one,
    mirroring PolicyBindingLifecycleState/PopulationPolicyBindingLifecycleState's
    own precedent for exactly this duplication -- so each can evolve
    independently."""
    assert PopulationFindingReviewResolution is not VerdictReviewResolution
    assert PopulationFindingReviewStatus is not VerdictReviewStatus
