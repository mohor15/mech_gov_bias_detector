"""`DisparitySignificanceTestPolicy` — pure logic, no DB. Mirrors
`test_adverse_impact_ratio.py`'s shape. Hand-computed reference values
per `docs/milestones/M8.md` §13.17: a z-statistic is easy to get subtly
wrong in a way that still "looks plausible" -- every FLAGGED/CLEAR
assertion here is checked against an independently, by-hand-derived
two-proportion z-statistic, not just internal consistency with the
implementation's own formula.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from gov_platform.population_engine.base import PopulationGroupCount, PopulationWindow
from gov_platform.population_engine.policies.disparity_significance_test import (
    DisparitySignificanceTestPolicy,
    _two_proportion_z,
)
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


def _hand_computed_z(n1: int, x1: int, n2: int, x2: int) -> float:
    """The two-proportion pooled z-statistic, computed independently from
    the implementation under test -- used as the reference oracle every
    test below checks against, per §13.17."""
    pooled_p = (x1 + x2) / (n1 + n2)
    standard_error = math.sqrt(pooled_p * (1 - pooled_p) * (1 / n1 + 1 / n2))
    return (x1 / n1 - x2 / n2) / standard_error


def test_empty_window_is_clear_with_insufficient_data_rationale() -> None:
    finding = DisparitySignificanceTestPolicy().evaluate(_window([], classification_snapshot={}))

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}
    assert finding.classification_snapshot == {}


def test_flags_a_statistically_significant_disparity() -> None:
    """Hand-computed: n1=100,x1=50 vs n2=100,x2=70 -> pooled p=0.6,
    SE=sqrt(0.6*0.4*0.02)=0.06928..., z=(0.5-0.7)/0.06928=-2.8868 --
    |z| >= 2.0 (the Castaneda default) -> FLAGGED."""
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ]
    )
    expected_z = _hand_computed_z(100, 50, 100, 70)
    assert expected_z == pytest.approx(-2.886751345948128, abs=1e-9)

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert finding.metric_values["race:Black"] == pytest.approx(expected_z, abs=1e-9)
    assert "race=Black" in finding.rationale


def test_clear_when_the_disparity_is_not_statistically_significant() -> None:
    """Hand-computed: n1=100,x1=60 vs n2=100,x2=65 -> pooled p=0.625,
    SE=sqrt(0.625*0.375*0.02)=0.068465..., z=(0.6-0.65)/0.068465=-0.7303
    -- |z| < 2.0 -> CLEAR."""
    window = _window(
        [
            _group("race", "Black", total=100, favorable=60),
            _group("race", "White", total=100, favorable=65),
        ]
    )
    expected_z = _hand_computed_z(100, 60, 100, 65)
    assert expected_z == pytest.approx(-0.7302967433, abs=1e-9)

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.metric_values["race:Black"] == pytest.approx(expected_z, abs=1e-9)


def test_z_statistic_exactly_at_the_critical_value_is_flagged() -> None:
    """Boundary check: |z| >= z_critical is inclusive. Using the exact
    hand-computed z from the first case as z_critical itself proves the
    boundary is closed, not open."""
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ],
        parameters={"z_critical": abs(_hand_computed_z(100, 50, 100, 70))},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED


def test_groups_below_the_minimum_sample_size_are_excluded() -> None:
    window = _window(
        [
            _group("race", "Black", total=5, favorable=2),  # far below _MINIMUM_GROUP_SIZE
            _group("race", "White", total=100, favorable=70),
        ]
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}


def test_a_single_eligible_group_is_insufficient_to_compare() -> None:
    window = _window([_group("race", "Black", total=100, favorable=50)])

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale


# --- statistical validity guards found during the M8 hostile-review pass
# (docs/milestones/M8.md §4.6) ---


def test_expected_cell_count_guard_excludes_a_group_that_clears_size_but_not_this() -> None:
    """40 decisions at a 2.5% approval rate clears minimum_group_size=30
    on raw count alone, but favorable_outcome_count=1 is far below the
    expected-cell-count floor of 5 -- must be excluded, not produce a
    statistically invalid z-statistic."""
    window = _window(
        [
            _group("race", "Black", total=40, favorable=1),
            _group("race", "White", total=40, favorable=40),
        ]
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}


def test_degenerate_variance_does_not_raise_zero_division_error() -> None:
    """Both groups at 0% approval -- would be a 0/0 pooled proportion if
    not excluded first. Also caught by the expected-cell-count guard
    (favorable_outcome_count=0 < 5), proving the two guards are
    consistent, not merely that neither happens to crash."""
    window = _window(
        [
            _group("race", "Black", total=40, favorable=0),
            _group("race", "White", total=40, favorable=0),
        ]
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.metric_values == {}


def test_multiple_attributes_aggregate_and_any_flag_flags_the_whole_finding() -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),  # flags (see above)
            _group("race", "White", total=100, favorable=70),
            _group("gender", "Female", total=100, favorable=63),  # clear (see above)
            _group("gender", "Male", total=100, favorable=65),
        ],
        classification_snapshot={"race": "DIRECT", "gender": "DIRECT"},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.FLAGGED
    assert "race:Black" in finding.metric_values
    assert "gender:Female" in finding.metric_values


def test_classification_snapshot_is_carried_through_unchanged() -> None:
    snapshot = {"race": "DIRECT", "gender": "DIRECT", "age": "DIRECT"}
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ],
        classification_snapshot=snapshot,
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.classification_snapshot == snapshot


def test_finding_identity_matches_the_policy_and_window() -> None:
    window = _window([])

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.population_policy_id == "disparity-significance-test"
    assert finding.population_policy_version == "0.1.0"
    assert finding.system_id == "sys-001"
    assert finding.window_start == _WINDOW_START
    assert finding.window_end == _WINDOW_END


# --- M8: admin-configurable parameters (docs/milestones/M8.md §4.3/§4.7) ---


def test_no_parameters_override_produces_the_documented_defaults_in_parameters_used() -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ]
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.parameters_used == {"z_critical": 2.0, "minimum_group_size": 30.0}


def test_a_valid_z_critical_override_changes_the_outcome() -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ],
        parameters={"z_critical": 3.0},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert finding.parameters_used["z_critical"] == 3.0


@pytest.mark.parametrize("bad_z_critical", [-1.0, 0.0, float("nan"), float("inf")])
def test_an_out_of_range_z_critical_override_falls_back_to_the_default(
    bad_z_critical: float,
) -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ],
        parameters={"z_critical": bad_z_critical},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.parameters_used["z_critical"] == 2.0
    assert "ignored out-of-range z_critical override" in finding.rationale


@pytest.mark.parametrize("bad_size", [-5.0, 0.0, float("nan"), float("inf")])
def test_an_out_of_range_minimum_group_size_override_falls_back_to_the_default(
    bad_size: float,
) -> None:
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ],
        parameters={"minimum_group_size": bad_size},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.parameters_used["minimum_group_size"] == 30.0
    assert "ignored out-of-range minimum_group_size override" in finding.rationale


def test_minimum_group_size_has_a_hard_structural_floor_of_two() -> None:
    window = _window(
        [
            _group("race", "Black", total=10, favorable=5),
            _group("race", "White", total=10, favorable=5),
        ],
        parameters={"minimum_group_size": 1},
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.parameters_used["minimum_group_size"] == 2.0


# --- `_two_proportion_z`'s defensive guards, exercised directly (unreachable
# through `evaluate()` once both groups have passed `_is_eligible` -- see
# the function's own docstring) ---


def test_two_proportion_z_returns_none_for_a_zero_pooled_proportion() -> None:
    zero_rate = _group("race", "Black", total=40, favorable=0)
    assert _two_proportion_z(zero_rate, zero_rate) is None


def test_two_proportion_z_returns_none_for_a_full_pooled_proportion() -> None:
    full_rate = _group("race", "Black", total=40, favorable=40)
    assert _two_proportion_z(full_rate, full_rate) is None


def test_evaluate_treats_a_defensive_none_comparison_as_insufficient_data(monkeypatch) -> None:
    """Confirms `evaluate()`'s own handling of `_two_proportion_z`
    returning `None` (the `_is_eligible` guarantee that makes this
    unreachable in practice notwithstanding) -- skips the comparison and
    falls back to "insufficient data" for that attribute, rather than
    silently dropping it from `insufficient_attributes` bookkeeping."""
    import gov_platform.population_engine.policies.disparity_significance_test as module

    monkeypatch.setattr(module, "_two_proportion_z", lambda group, reference: None)
    window = _window(
        [
            _group("race", "Black", total=100, favorable=50),
            _group("race", "White", total=100, favorable=70),
        ]
    )

    finding = DisparitySignificanceTestPolicy().evaluate(window)

    assert finding.outcome is PopulationFindingOutcome.CLEAR
    assert "insufficient data" in finding.rationale
    assert finding.metric_values == {}
