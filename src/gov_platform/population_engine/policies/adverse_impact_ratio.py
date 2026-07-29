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

M8 (architecture §10): `threshold`/`minimum_group_size` are now
admin-configurable per binding, resolved from `window.parameters`
(`docs/milestones/M8.md` §4.3) with a fallback to the exact hardcoded
defaults above when no override is given -- a binding with no
`parameters` produces byte-identical output to every M6/M7 behavior, no
version bump (§13.7). An out-of-range override (`threshold` outside
`(0, 1]`) is rejected in favor of the built-in default, not silently
applied (§4.7/§13.16's hostile-review-pass finding) -- an unauthenticated
admin surface accepting an unvalidated threshold is a direct lever
against this platform's own bias-detection purpose. `minimum_group_size`
additionally has a hard, code-enforced structural floor of 2 beneath any
override -- below that, "compare at least two groups" is not a judgment
call, it is a precondition this policy's own math requires (§13.16).
Every resolved, effective value (post-fallback, post-floor) is recorded
in the returned `PopulationFinding.parameters_used`, the same
point-in-time-reproducibility guarantee `classification_snapshot`
already has (§4.5).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.plugins.registry import register_population_policy
from gov_platform.population_engine.base import PopulationPolicy, PopulationWindow
from gov_platform.population_engine.policies._shared import group_by_attribute
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome

_RATIO_THRESHOLD = 0.8  # EEOC "four-fifths rule", 29 CFR § 1607.4(D)
_MINIMUM_GROUP_SIZE = 30  # below this, an approval-rate ratio is noise, not signal
_STRUCTURAL_MINIMUM_GROUP_SIZE = 2  # hard floor: "compare at least two groups" (§13.16)


def _resolve_parameters(parameters: dict[str, float]) -> tuple[float, int, list[str]]:
    """Resolves this policy's effective `(threshold, minimum_group_size)`
    from a binding's `parameters`, falling back to the built-in defaults
    for an absent or out-of-range override. Returns the resolved values
    plus any human-readable fallback notices, folded into the finding's
    `rationale` so a rejected override is never silent (§4.7)."""
    notices: list[str] = []

    threshold = parameters.get("threshold", _RATIO_THRESHOLD)
    if not math.isfinite(threshold) or not (0 < threshold <= 1):
        notices.append(
            f"ignored out-of-range threshold override {threshold!r} "
            f"(must be in (0, 1]); using default {_RATIO_THRESHOLD}"
        )
        threshold = _RATIO_THRESHOLD

    minimum_group_size_raw = parameters.get("minimum_group_size", float(_MINIMUM_GROUP_SIZE))
    if not math.isfinite(minimum_group_size_raw) or minimum_group_size_raw < 1:
        notices.append(
            f"ignored out-of-range minimum_group_size override {minimum_group_size_raw!r} "
            f"(must be >= 1); using default {_MINIMUM_GROUP_SIZE}"
        )
        minimum_group_size = _MINIMUM_GROUP_SIZE
    else:
        minimum_group_size = int(minimum_group_size_raw)

    # A hard, code-enforced structural floor, not a judgment-call
    # fallback: comparing fewer than two groups is not a statistically
    # noisier choice an admin might deliberately make, it is a
    # precondition this policy's math cannot proceed without (§13.16).
    minimum_group_size = max(minimum_group_size, _STRUCTURAL_MINIMUM_GROUP_SIZE)

    return threshold, minimum_group_size, notices


@register_population_policy
class AdverseImpactRatioPolicy(PopulationPolicy):
    """Flags a window when any `DIRECT`-classified protected attribute's
    value shows a favorable-outcome rate under `_RATIO_THRESHOLD` of the
    highest-rate value for that same attribute, among values with at
    least `_MINIMUM_GROUP_SIZE` decisions."""

    population_policy_id = "adverse-impact-ratio"
    version = "0.1.0"

    def evaluate(self, window: PopulationWindow) -> PopulationFinding:
        threshold, minimum_group_size, notices = _resolve_parameters(window.parameters)
        by_attribute = group_by_attribute(window.group_counts)

        metric_values: dict[str, float] = {}
        flagged_details: list[str] = []
        insufficient_attributes: list[str] = []
        any_ratio_computed = False

        for attribute_name in sorted(by_attribute):
            eligible = [
                g for g in by_attribute[attribute_name] if g.total_count >= minimum_group_size
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
                if ratio < threshold:
                    flagged_details.append(
                        f"{attribute_name}={attribute_value} approval-rate ratio "
                        f"{ratio:.3f} is below the {threshold} threshold"
                    )

        if flagged_details:
            outcome = PopulationFindingOutcome.FLAGGED
            rationale = "; ".join(flagged_details)
        elif any_ratio_computed:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = (
                "every protected-attribute value's approval-rate ratio is at or above "
                f"the {threshold} threshold"
            )
        else:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = "insufficient data to compute an adverse impact ratio for this window"
            if insufficient_attributes:
                rationale += f" (attribute(s): {', '.join(insufficient_attributes)})"

        if notices:
            rationale += " [" + "; ".join(notices) + "]"

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
            parameters_used={
                "threshold": threshold,
                "minimum_group_size": float(minimum_group_size),
            },
            rationale=rationale,
            evaluated_at=datetime.now(UTC),
        )
