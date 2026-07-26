"""`DirectAttributeInInputsPolicy` — the first policy that needs both
outcome branches exercised. Uses the default (real) `ProtectedAttributeResolver`
against its fixed `FINANCE` domain -- no mocking needed since the resolver
is pure and DB-free.
"""

from __future__ import annotations

from gov_platform.policy_engine.policies.direct_attribute_in_inputs import (
    DirectAttributeInInputsPolicy,
)
from gov_platform.schemas.finding import FindingOutcome


def test_clear_when_no_protected_attribute_supplied(make_decision_event) -> None:
    event = make_decision_event(protected_attribute_refs={}, input_features={"annual_income": 1.0})

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
    assert finding.metric_values["direct_attributes_in_inputs_count"] == 0.0


def test_clear_when_direct_attribute_supplied_but_kept_out_of_inputs(make_decision_event) -> None:
    event = make_decision_event(
        protected_attribute_refs={"race": "Black"},
        input_features={"annual_income": 1.0},
    )

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR


def test_flagged_when_a_direct_attribute_leaks_into_inputs(make_decision_event) -> None:
    event = make_decision_event(
        protected_attribute_refs={"race": "Black"},
        input_features={"race": 1.0, "annual_income": 1.0},
    )

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.FLAGGED
    assert finding.metric_values["direct_attributes_in_inputs_count"] == 1.0
    assert "race" in finding.rationale
    assert finding.decision_event_id == event.event_id
    assert finding.policy_id == "direct-attribute-in-inputs"


def test_flagged_lists_every_leaked_direct_attribute(make_decision_event) -> None:
    event = make_decision_event(
        protected_attribute_refs={"race": "Black", "gender": "F"},
        input_features={"race": 1.0, "gender": 1.0, "annual_income": 1.0},
    )

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.FLAGGED
    assert finding.metric_values["direct_attributes_in_inputs_count"] == 2.0
    assert "gender" in finding.rationale
    assert "race" in finding.rationale


def test_clear_when_a_withheld_attribute_happens_to_match_an_input_key(make_decision_event) -> None:
    # Documented scope boundary (see the policy's module docstring): an
    # *undisclosed* protected attribute silently used as a model input is
    # not detected by this check -- only attributes actually classified
    # DIRECT are. Asserting this so the boundary reads as intentional, not
    # an untested gap.
    event = make_decision_event(
        protected_attribute_refs={},
        input_features={"race": 1.0, "annual_income": 1.0},
    )

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR


def test_clear_when_a_proxied_attribute_leaks_into_inputs(make_decision_event) -> None:
    # zip_code resolves to PROXIED, not DIRECT -- this policy only checks
    # DIRECT attributes, by design (see module docstring).
    event = make_decision_event(
        protected_attribute_refs={"zip_code": "12345"},
        input_features={"zip_code": 1.0, "annual_income": 1.0},
    )

    finding = DirectAttributeInInputsPolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
