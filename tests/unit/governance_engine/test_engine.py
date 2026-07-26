from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    engine = GovernanceEngine(policies=[AlwaysAllowPolicy()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 1
    assert verdict.findings[0].outcome is FindingOutcome.CLEAR
    assert verdict.decision_event_id == make_decision_event().event_id


def test_governance_engine_wraps_flagged_finding_as_flagged(make_decision_event) -> None:
    engine = GovernanceEngine(policies=[_FlaggingPolicy()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.FLAGGED
    assert verdict.findings[0].outcome is FindingOutcome.FLAGGED


def test_each_verdict_gets_a_unique_id(make_decision_event) -> None:
    engine = GovernanceEngine(policies=[AlwaysAllowPolicy()])
    event = make_decision_event()

    first = engine.govern(event)
    second = engine.govern(event)

    assert first.verdict_id != second.verdict_id


def test_constructing_with_no_policies_raises() -> None:
    with pytest.raises(ValueError, match="at least one Policy"):
        GovernanceEngine(policies=[])


# --- M4: policy plurality / aggregation matrix ------------------------


def test_all_clear_policies_aggregate_to_allow(make_decision_event) -> None:
    engine = GovernanceEngine(policies=[AlwaysAllowPolicy(), AlwaysAllowPolicy()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.ALLOW
    assert len(verdict.findings) == 2
    assert all(f.outcome is FindingOutcome.CLEAR for f in verdict.findings)


def test_one_dissenting_policy_among_several_agreers_flags_the_whole_verdict(
    make_decision_event,
) -> None:
    # The real disagreement-surfacing case: two policies clear, one
    # flags -- "most restrictive wins", and all three opinions are still
    # present in the verdict, not just the deciding one.
    engine = GovernanceEngine(
        policies=[AlwaysAllowPolicy(), _FlaggingPolicy(), AlwaysAllowPolicy()]
    )
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.FLAGGED
    assert len(verdict.findings) == 3
    outcomes = [f.outcome for f in verdict.findings]
    assert outcomes.count(FindingOutcome.CLEAR) == 2
    assert outcomes.count(FindingOutcome.FLAGGED) == 1


def test_all_flagged_policies_aggregate_to_flagged(make_decision_event) -> None:
    engine = GovernanceEngine(policies=[_FlaggingPolicy(), _FlaggingPolicy()])
    verdict = engine.govern(make_decision_event())

    assert verdict.status is VerdictStatus.FLAGGED
    assert len(verdict.findings) == 2


def test_findings_are_built_in_constructor_declared_order(make_decision_event) -> None:
    engine = GovernanceEngine(policies=[_FlaggingPolicy(), AlwaysAllowPolicy()])
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

    engine = GovernanceEngine(policies=[AlwaysAllowPolicy(), _RaisingPolicy()])

    with pytest.raises(RuntimeError, match="simulated policy failure"):
        engine.govern(make_decision_event())
