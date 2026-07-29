"""`population_engine/policies/_shared.py`'s `group_by_attribute` helper
in isolation -- the one piece of logic M8 extracted from
`adverse_impact_ratio.py` once `disparity_significance_test.py` became a
genuine second caller (`docs/milestones/M8.md` §4.6/§13.8).
"""

from __future__ import annotations

from gov_platform.population_engine.base import PopulationGroupCount
from gov_platform.population_engine.policies._shared import group_by_attribute


def _group(name: str, value: str, total: int, favorable: int) -> PopulationGroupCount:
    return PopulationGroupCount(
        attribute_name=name,
        attribute_value=value,
        total_count=total,
        favorable_outcome_count=favorable,
    )


def test_empty_input_produces_an_empty_mapping() -> None:
    assert group_by_attribute([]) == {}


def test_groups_are_keyed_by_attribute_name() -> None:
    groups = [
        _group("race", "Black", total=10, favorable=5),
        _group("race", "White", total=10, favorable=8),
        _group("gender", "Female", total=10, favorable=6),
    ]

    by_attribute = group_by_attribute(groups)

    assert set(by_attribute) == {"race", "gender"}
    assert len(by_attribute["race"]) == 2
    assert len(by_attribute["gender"]) == 1


def test_grouping_preserves_input_order_within_each_attribute() -> None:
    black = _group("race", "Black", total=10, favorable=5)
    white = _group("race", "White", total=10, favorable=8)

    by_attribute = group_by_attribute([black, white])

    assert by_attribute["race"] == [black, white]
