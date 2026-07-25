from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.policy_engine.base import Policy
from gov_platform.policy_engine.policies.always_allow import AlwaysAllowPolicy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import VerdictStatus


class _FlaggingPolicy(Policy):
    """Test double proving GovernanceEngine reacts to a FLAGGED Finding —
    exercising the branch AlwaysAllowPolicy alone never can."""

    policy_id = "test-flagging-policy"
    version = "0.0.1"

    def evaluate(self, event: DecisionEvent) -> Finding:
        return Finding(
            finding_id="find-flag",
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.FLAGGED,
            confidence=0.9,
            rationale="test double: always flags",
            metric_values={},
            evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_governance_engine_wraps_clear_finding_as_allow(make_decision_event) -> None:
    engine = GovernanceEngine(policy=AlwaysAllowPolicy())
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 1
    assert verdict.findings[0].outcome is FindingOutcome.CLEAR
    assert verdict.decision_event_id == make_decision_event().event_id


def test_governance_engine_wraps_flagged_finding_as_flagged(make_decision_event) -> None:
    engine = GovernanceEngine(policy=_FlaggingPolicy())
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.FLAGGED
    assert verdict.findings[0].outcome is FindingOutcome.FLAGGED


def test_each_verdict_gets_a_unique_id(make_decision_event) -> None:
    engine = GovernanceEngine(policy=AlwaysAllowPolicy())
    event = make_decision_event()

    first = engine.govern(event)
    second = engine.govern(event)

    assert first.verdict_id != second.verdict_id
