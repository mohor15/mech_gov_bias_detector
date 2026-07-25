from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus


def _finding() -> Finding:
    return Finding(
        finding_id="find-001",
        decision_event_id="evt-001",
        policy_id="always-allow",
        policy_version="0.1.0",
        outcome=FindingOutcome.CLEAR,
        confidence=1.0,
        rationale="test rationale",
        metric_values={},
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_valid_verdict_constructs() -> None:
    verdict = GovernanceVerdict(
        verdict_id="verd-001",
        decision_event_id="evt-001",
        status=VerdictStatus.ALLOW,
        findings=[_finding()],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 1


def test_verdict_requires_at_least_one_finding() -> None:
    with pytest.raises(ValidationError):
        GovernanceVerdict(
            verdict_id="verd-001",
            decision_event_id="evt-001",
            status=VerdictStatus.ALLOW,
            findings=[],
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_verdict_status_has_exactly_two_values() -> None:
    # Documents the M0 decision explicitly: the full four-state model
    # (architecture §8.2) is M5 scope. This test should fail loudly the day
    # someone adds ESCALATE_FOR_REVIEW/RECOMMEND_HOLD outside that milestone.
    assert {member.value for member in VerdictStatus} == {"ALLOW", "FLAGGED"}
