"""`AdverseImpactRatioPolicy` — pure logic, no DB. `PopulationWindow` is
constructed directly with hand-built `PopulationGroupCount` rows rather
than going through `population_engine/window.py`, which is its own,
separately (Postgres-)tested concern.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gov_platform.population_engine.base import PopulationGroupCount, PopulationWindow
from gov_platform.population_engine.policies.adverse_impact_ratio import AdverseImpactRatioPolicy
from gov_platform.schemas.population_finding import PopulationFindingOutcome

_WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 1, 2, tzinfo=UTC)


_DEFAULT_SNAPSHOT = {"race": "DIRECT"}


def _window(
    group_counts: list[PopulationGroupCount],
    classification_snapshot: dict[str, str] = _DEFAULT_SNAPSHOT,
    parameters: dict[str, float] | None = None,
) -> PopulationWindow:
    return PopulationWindow(
        system_id="sys-001",
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        group_counts=group_counts,
        classification_snapshot=classification_snapshot,
        parameters=parameters or {},
    )


def _group(name: str, value: str, total: int, favorable: int) -> PopulationGroupCount:
    return PopulationGroupCount(
        attribute_name=name,
        attribute_value=value,
        total_count=total,
        favorable_outcome_count=favorable,
    )


def test_empty_window_is_clear_with_insufficient_data_rationale() -> None:
    finding = AdverseImpactRatioPolicy().evaluate(_window([], classification_snapshot={}))

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}
    assert finding.classification_snapshot == {}


def test_flags_a_group_whose_ratio_falls_below_the_threshold() -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),  # rate 0.75
            _group("race", "White", total=40, favorable=40),  # rate 1.0, reference
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert finding.metric_values["race:Black"] == 0.75
    assert finding.metric_values["race:White"] == 1.0
    assert "race=Black" in finding.rationale


def test_clear_when_every_group_is_within_the_threshold() -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=36),  # rate 0.9
            _group("race", "White", total=40, favorable=40),  # rate 1.0
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.metric_values["race:Black"] == 0.9


def test_ratio_exactly_at_the_threshold_is_not_flagged() -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=80),  # rate 0.80
            _group("race", "White", total=100, favorable=100),  # rate 1.0 -> ratio 0.80
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.metric_values["race:Black"] == 0.80


def test_groups_below_the_minimum_sample_size_are_excluded() -> None:
    window = _window(
        [
            _group("race", "Black", total=5, favorable=0),  # far below _MINIMUM_GROUP_SIZE
            _group("race", "White", total=40, favorable=40),
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}


def test_a_single_eligible_group_is_insufficient_to_compare() -> None:
    window = _window([_group("race", "Black", total=40, favorable=30)])

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale


def test_a_zero_reference_rate_does_not_divide_by_zero() -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=0),
            _group("race", "White", total=40, favorable=0),
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.metric_values == {}


def test_multiple_attributes_aggregate_and_any_flag_flags_the_whole_finding() -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),  # 0.75 -> flags
            _group("race", "White", total=40, favorable=40),
            _group("gender", "Female", total=40, favorable=38),  # 0.95 -> clear
            _group("gender", "Male", total=40, favorable=40),
        ],
        classification_snapshot={"race": "DIRECT", "gender": "DIRECT"},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert finding.metric_values["race:Black"] == 0.75
    assert finding.metric_values["gender:Female"] == 0.95


def test_classification_snapshot_is_carried_through_unchanged() -> None:
    snapshot = {"race": "DIRECT", "gender": "DIRECT", "age": "DIRECT"}
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),
            _group("race", "White", total=40, favorable=40),
        ],
        classification_snapshot=snapshot,
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.classification_snapshot == snapshot


def test_finding_identity_matches_the_policy_and_window() -> None:
    window = _window([])

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.population_policy_id == "adverse-impact-ratio"
    assert finding.population_policy_version == "0.1.0"
    assert finding.system_id == "sys-001"
    assert finding.window_start == _WINDOW_START
    assert finding.window_end == _WINDOW_END


# --- M8: admin-configurable parameters (docs/milestones/M8.md §4.3/§4.7) ---


def test_no_parameters_override_produces_the_exact_pre_m8_defaults_in_parameters_used() -> None:
    """Regression proof for §13.7: a binding with no `parameters` produces
    byte-identical behavior to before M8, and `parameters_used` reports
    the built-in defaults, not an empty dict."""
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),  # rate 0.75
            _group("race", "White", total=40, favorable=40),
        ]
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert finding.parameters_used == {"threshold": 0.8, "minimum_group_size": 30.0}


def test_a_valid_threshold_override_changes_the_outcome() -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),  # rate 0.75
            _group("race", "White", total=40, favorable=40),
        ],
        parameters={"threshold": 0.7},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.parameters_used["threshold"] == 0.7


def test_a_valid_minimum_group_size_override_is_honored() -> None:
    window = _window(
        [
            _group("race", "Black", total=10, favorable=0),
            _group("race", "White", total=10, favorable=10),
        ],
        parameters={"minimum_group_size": 5},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert finding.parameters_used["minimum_group_size"] == 5.0


@pytest.mark.parametrize("bad_threshold", [-1.0, 0.0, 1.5, float("nan"), float("inf")])
def test_an_out_of_range_threshold_override_falls_back_to_the_default(bad_threshold: float) -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),
            _group("race", "White", total=40, favorable=40),
        ],
        parameters={"threshold": bad_threshold},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.parameters_used["threshold"] == 0.8
    assert "ignored out-of-range threshold override" in finding.rationale


@pytest.mark.parametrize("bad_size", [-5.0, 0.0, float("nan"), float("inf")])
def test_an_out_of_range_minimum_group_size_override_falls_back_to_the_default(
    bad_size: float,
) -> None:
    window = _window(
        [
            _group("race", "Black", total=40, favorable=30),
            _group("race", "White", total=40, favorable=40),
        ],
        parameters={"minimum_group_size": bad_size},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.parameters_used["minimum_group_size"] == 30.0
    assert "ignored out-of-range minimum_group_size override" in finding.rationale


def test_minimum_group_size_has_a_hard_structural_floor_of_two() -> None:
    """§13.16: an admin can configure minimum_group_size below the
    built-in default, but not below the hard structural floor of 2 --
    "compare at least two groups" is a precondition, not a judgment call,
    and this override is otherwise valid (positive, finite), so no
    fallback notice is expected."""
    window = _window(
        [
            _group("race", "Black", total=1, favorable=0),
            _group("race", "White", total=1, favorable=1),
        ],
        parameters={"minimum_group_size": 1},
    )

    finding = AdverseImpactRatioPolicy().evaluate(window)

    assert finding.parameters_used["minimum_group_size"] == 2.0
    assert "ignored" not in finding.rationale
