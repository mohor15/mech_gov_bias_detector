"""`AdverseImpactRatioPolicy` — pure logic, no DB. `PopulationWindow` is
constructed directly with hand-built `PopulationGroupCount` rows rather
than going through `population_engine/window.py`, which is its own,
separately (Postgres-)tested concern.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.population_engine.base import PopulationGroupCount, PopulationWindow
from gov_platform.population_engine.policies.adverse_impact_ratio import AdverseImpactRatioPolicy
from gov_platform.schemas.population_finding import PopulationFindingOutcome

_WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 1, 2, tzinfo=UTC)


_DEFAULT_SNAPSHOT = {"race": "DIRECT"}


def _window(
    group_counts: list[PopulationGroupCount],
    classification_snapshot: dict[str, str] = _DEFAULT_SNAPSHOT,
) -> PopulationWindow:
    return PopulationWindow(
        system_id="sys-001",
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        group_counts=group_counts,
        classification_snapshot=classification_snapshot,
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
