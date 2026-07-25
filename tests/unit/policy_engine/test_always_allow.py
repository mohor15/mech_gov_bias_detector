from __future__ import annotations

from gov_platform.policy_engine.policies.always_allow import AlwaysAllowPolicy
from gov_platform.schemas.finding import FindingOutcome


def test_always_allow_clears_every_event(make_decision_event) -> None:
    policy = AlwaysAllowPolicy()
    event = make_decision_event()

    finding = policy.evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
    assert finding.confidence == 1.0
    assert finding.decision_event_id == event.event_id
    assert finding.policy_id == "always-allow"


def test_always_allow_clears_event_with_protected_attributes(make_decision_event) -> None:
    # M0's only policy is deliberately naive — it does not look at protected
    # attributes at all. Asserting that here documents the boundary: real
    # attribute-aware judgment is M2's hard-gate policy, not this one.
    event = make_decision_event(protected_attribute_refs={"country": "India"})
    finding = AlwaysAllowPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
