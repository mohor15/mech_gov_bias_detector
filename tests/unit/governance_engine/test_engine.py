from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gov_platform.governance_engine.engine import GovernanceEngine, GoverningPolicy
from gov_platform.policy_engine.base import Policy
from gov_platform.policy_engine.policies.always_allow import AlwaysAllowPolicy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.policy_binding import PolicySeverity
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


def _allow(severity: PolicySeverity = PolicySeverity.LOW) -> GoverningPolicy:
    return GoverningPolicy(policy=AlwaysAllowPolicy(), severity=severity)


def _flag(severity: PolicySeverity) -> GoverningPolicy:
    return GoverningPolicy(policy=_FlaggingPolicy(), severity=severity)


def test_governance_engine_wraps_clear_finding_as_allow(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_allow()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 1
    assert verdict.findings[0].outcome is FindingOutcome.CLEAR
    assert verdict.decision_event_id == make_decision_event().event_id


def test_each_verdict_gets_a_unique_id(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_allow()])
    event = make_decision_event()

    first = engine.govern(event)
    second = engine.govern(event)

    assert first.verdict_id != second.verdict_id


def test_constructing_with_no_policies_raises() -> None:
    with pytest.raises(ValueError, match="at least one GoverningPolicy"):
        GovernanceEngine(governing_policies=[])


# --- M4: policy plurality / aggregation matrix ------------------------


def test_all_clear_policies_aggregate_to_allow(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_allow(), _allow()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 2
    assert all(f.outcome is FindingOutcome.CLEAR for f in verdict.findings)


def test_findings_are_built_in_constructor_declared_order(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_flag(PolicySeverity.LOW), _allow()])
    verdict = engine.govern(make_decision_event())

    assert verdict.findings[0].policy_id == "test-flagging-policy"
    assert verdict.findings[1].policy_id == "always-allow"


def test_a_raising_policy_propagates_instead_of_producing_a_partial_verdict(
    make_decision_event,
) -> None:
    class _RaisingPolicy(Policy):
        policy_id = "test-raising-policy"
        version = "0.0.1"

        def evaluate(self, event: DecisionEvent) -> Finding:
            raise RuntimeError("simulated policy failure")

    engine = GovernanceEngine(
        governing_policies=[
            _allow(),
            GoverningPolicy(policy=_RaisingPolicy(), severity=PolicySeverity.LOW),
        ]
    )

    with pytest.raises(RuntimeError, match="simulated policy failure"):
        engine.govern(make_decision_event())


# --- M5: severity-driven escalation ------------------------------------


def test_a_low_severity_flag_allows_with_flag(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_flag(PolicySeverity.LOW)])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW_WITH_FLAG


def test_a_medium_severity_flag_escalates_for_review(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_flag(PolicySeverity.MEDIUM)])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ESCALATE_FOR_REVIEW


def test_a_high_severity_flag_recommends_hold(make_decision_event) -> None:
    engine = GovernanceEngine(governing_policies=[_flag(PolicySeverity.HIGH)])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.RECOMMEND_HOLD


def test_the_highest_severity_among_several_flags_wins(make_decision_event) -> None:
    # Most-restrictive-wins: a LOW flag alongside a HIGH flag must not
    # water down the verdict to ALLOW_WITH_FLAG.
    engine = GovernanceEngine(
        governing_policies=[
            _flag(PolicySeverity.LOW),
            _allow(),
            _flag(PolicySeverity.HIGH),
            _flag(PolicySeverity.MEDIUM),
        ]
    )
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.RECOMMEND_HOLD
    assert len(verdict.findings) == 4


def test_a_clear_finding_from_a_high_severity_binding_does_not_escalate(
    make_decision_event,
) -> None:
    # Severity only matters for findings that actually flag -- a policy
    # bound at HIGH severity that clears contributes nothing to escalation.
    engine = GovernanceEngine(governing_policies=[_allow(severity=PolicySeverity.HIGH)])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
