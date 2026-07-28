"""The M6 reference population policy — architecture §7.

Adverse impact ratio, computed the standard way (the EEOC "four-fifths
rule", 29 CFR § 1607.4(D)): for each `DIRECT`-classified protected
attribute, compare each value's favorable-outcome (approval) rate against
the highest-rate value among that attribute's values; `FLAGGED` if any
ratio falls under `_RATIO_THRESHOLD`. One concrete metric, computed for
whichever attributes `population_engine/window.py` already determined are
`DIRECT` for the system's domain — not a general population-metrics
framework. See `docs/milestones/M6.md` §4.4/§13.9.

`_MINIMUM_GROUP_SIZE` is an implementation-readiness requirement the
hostile-review pass added (`docs/milestones/M6.md` §4.5): a group with a
handful of decisions can produce a mathematically valid but statistically
meaningless ratio. A protected-attribute value with fewer than
`_MINIMUM_GROUP_SIZE` decisions in the window is excluded from the ratio
computation for that attribute; if fewer than two values have enough data
to compare, this policy reports `CLEAR` with an explicit
"insufficient data" rationale, not a `FLAGGED` verdict built on noise. 30
is a conventional floor for a proportion comparison to be meaningful, not
a value cited to a specific regulatory source the way `_RATIO_THRESHOLD`
is -- named here for the same reason `HighDebtRatioGatePolicy`'s threshold
is named: precise provenance, not silence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.plugins.registry import register_population_policy
from gov_platform.population_engine.base import (
    PopulationGroupCount,
    PopulationPolicy,
    PopulationWindow,
)
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome

_RATIO_THRESHOLD = 0.8  # EEOC "four-fifths rule", 29 CFR § 1607.4(D)
_MINIMUM_GROUP_SIZE = 30  # below this, an approval-rate ratio is noise, not signal


@register_population_policy
class AdverseImpactRatioPolicy(PopulationPolicy):
    """Flags a window when any `DIRECT`-classified protected attribute's
    value shows a favorable-outcome rate under `_RATIO_THRESHOLD` of the
    highest-rate value for that same attribute, among values with at
    least `_MINIMUM_GROUP_SIZE` decisions."""

    population_policy_id = "adverse-impact-ratio"
    version = "0.1.0"

    def evaluate(self, window: PopulationWindow) -> PopulationFinding:
        by_attribute: dict[str, list[PopulationGroupCount]] = defaultdict(list)
        for group in window.group_counts:
            by_attribute[group.attribute_name].append(group)

        metric_values: dict[str, float] = {}
        flagged_details: list[str] = []
        insufficient_attributes: list[str] = []
        any_ratio_computed = False

        for attribute_name in sorted(by_attribute):
            eligible = [
                g for g in by_attribute[attribute_name] if g.total_count >= _MINIMUM_GROUP_SIZE
            ]
            if len(eligible) < 2:
                insufficient_attributes.append(attribute_name)
                continue

            rates = {g.attribute_value: g.favorable_outcome_count / g.total_count for g in eligible}
            reference_rate = max(rates.values())
            if reference_rate == 0:
                # Nobody in any sufficiently-sized group got a favorable
                # outcome -- every ratio would be an undefined 0/0, not a
                # real disparity signal.
                insufficient_attributes.append(attribute_name)
                continue

            any_ratio_computed = True
            for attribute_value, rate in sorted(rates.items()):
                ratio = rate / reference_rate
                metric_values[f"{attribute_name}:{attribute_value}"] = ratio
                if ratio < _RATIO_THRESHOLD:
                    flagged_details.append(
                        f"{attribute_name}={attribute_value} approval-rate ratio "
                        f"{ratio:.3f} is below the {_RATIO_THRESHOLD} threshold"
                    )

        if flagged_details:
            outcome = PopulationFindingOutcome.FLAGGED
            rationale = "; ".join(flagged_details)
        elif any_ratio_computed:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = (
                "every protected-attribute value's approval-rate ratio is at or above "
                f"the {_RATIO_THRESHOLD} threshold"
            )
        else:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = "insufficient data to compute an adverse impact ratio for this window"
            if insufficient_attributes:
                rationale += f" (attribute(s): {', '.join(insufficient_attributes)})"

        return PopulationFinding(
            population_finding_id=str(uuid4()),
            population_policy_id=self.population_policy_id,
            population_policy_version=self.version,
            system_id=window.system_id,
            window_start=window.window_start,
            window_end=window.window_end,
            outcome=outcome,
            metric_values=metric_values,
            classification_snapshot=window.classification_snapshot,
            rationale=rationale,
            evaluated_at=datetime.now(UTC),
        )
