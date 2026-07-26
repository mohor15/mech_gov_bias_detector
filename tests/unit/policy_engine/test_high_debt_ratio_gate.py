from __future__ import annotations

from gov_platform.policy_engine.policies.high_debt_ratio_gate import (
    HighDebtRatioGatePolicy,
)
from gov_platform.schemas.finding import FindingOutcome


def test_clear_when_debt_to_income_is_within_the_limit(make_decision_event) -> None:
    event = make_decision_event(input_features={"debt_to_income": 0.30})

    finding = HighDebtRatioGatePolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
    assert finding.metric_values == {"debt_to_income": 0.30}


def test_clear_when_debt_to_income_exactly_equals_the_limit(make_decision_event) -> None:
    event = make_decision_event(input_features={"debt_to_income": 0.43})

    finding = HighDebtRatioGatePolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR


def test_flagged_when_debt_to_income_exceeds_the_limit(make_decision_event) -> None:
    event = make_decision_event(input_features={"debt_to_income": 0.55})

    finding = HighDebtRatioGatePolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.FLAGGED
    assert finding.metric_values == {"debt_to_income": 0.55}
    assert "0.55" in finding.rationale
    assert finding.policy_id == "high-debt-ratio-gate"


def test_clear_when_debt_to_income_is_not_supplied_at_all(make_decision_event) -> None:
    event = make_decision_event(input_features={"annual_income": 65000.0})

    finding = HighDebtRatioGatePolicy().evaluate(event)

    assert finding.outcome is FindingOutcome.CLEAR
    assert finding.metric_values == {}
    assert "not supplied" in finding.rationale
