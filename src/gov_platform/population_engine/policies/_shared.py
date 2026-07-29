"""Grouping helper shared by every concrete `PopulationPolicy` — M8,
architecture §10.

Not shared at M6, deliberately: with exactly one concrete policy
(`adverse_impact_ratio.py`), extracting this five-line `defaultdict` loop
had no second caller to justify it — pure speculation. `disparity_significance_test.py`
(M8) is the first genuine second case, and needs the identical step — see
`docs/milestones/M8.md` §4.6/§13.8 for why only this much is shared:
eligibility filtering (each policy's own minimum-group-size floor) and
metric computation (ratio vs. z-statistic) stay in each policy, because
those genuinely differ between the two.
"""

from __future__ import annotations

from collections import defaultdict

from gov_platform.population_engine.base import PopulationGroupCount


def group_by_attribute(
    group_counts: list[PopulationGroupCount],
) -> dict[str, list[PopulationGroupCount]]:
    """Every `PopulationGroupCount` in `group_counts`, keyed by its own
    `attribute_name` — the unit both concrete policies iterate over,
    one comparison per protected attribute."""
    by_attribute: dict[str, list[PopulationGroupCount]] = defaultdict(list)
    for group in group_counts:
        by_attribute[group.attribute_name].append(group)
    return by_attribute
