"""The M8 second population policy — architecture §10 (Evaluation
Framework).

A two-proportion z-test for statistical significance of a disparity
between a protected-attribute value's favorable-outcome rate and the
reference (highest-rate) value's rate for the same attribute — genuinely
different in *kind* from `AdverseImpactRatioPolicy`'s practical-
significance ratio threshold, not a second ratio-threshold variant. Real
EEOC/OFCCP disparate-impact analysis pairs exactly these two tests in
practice: the four-fifths rule for practical significance, and a
standard-deviations/statistical-significance test for whether a gap could
plausibly be chance. *Castaneda v. Partida*, 430 U.S. 482 (1977), is the
commonly cited legal precedent for treating a disparity of two or more
standard deviations from the expected value as evidence warranting
scrutiny — `_Z_CRITICAL`'s default. See `docs/milestones/M8.md` §4.2/§13.6.

`metric_values` records each comparison's `z` statistic, not a p-value —
`z_critical` is the parameter an admin actually sets, matching how the
legal convention itself is phrased in standard deviations, not p-values.
No new external dependency: this is closed-form arithmetic; converting a
z-statistic to a p-value, if ever wanted, needs only the stdlib
`statistics.NormalDist` (unused here — `z_critical` is compared directly,
per §13.11).

Two statistical-validity guards beyond `AdverseImpactRatioPolicy`'s own
`minimum_group_size` floor, found during this milestone's own
hostile-review pass (`docs/milestones/M8.md` §4.6) — both folded into
this policy's own per-group eligibility filter, alongside
`minimum_group_size`, rather than checked only pairwise at computation
time:

- **Expected-cell-count validity**: the normal approximation this test
  relies on additionally requires each compared group's *expected*
  favorable and unfavorable counts to be large enough — the standard
  rule of thumb, `n * p >= 5` and `n * (1 - p) >= 5` using the group's own
  observed rate, which (since `p = favorable_outcome_count / total_count`)
  reduces to `favorable_outcome_count >= 5` and
  `total_count - favorable_outcome_count >= 5`. A group can clear
  `minimum_group_size` on raw count alone while still having a rate
  extreme enough that this fails (e.g. 40 decisions at a 3% approval
  rate) — the test would still compute a number, and that number would
  still look like a legitimate z-statistic, while being statistically
  invalid.
- **Degenerate variance**: a two-proportion z-test's standard error is
  `sqrt(p * (1 - p) * (1/n1 + 1/n2))` for pooled proportion `p`; if `p` is
  exactly `0` or `1`, the standard error is `0` and the z-statistic is
  undefined. Requiring every eligible group to individually clear the
  expected-cell-count guard above already guarantees each group's own
  rate is strictly between `0` and `1`, which in turn guarantees any
  pooled proportion of two eligible groups is too — this guard is kept as
  an explicit, defensive check in `_two_proportion_z` regardless, so this
  policy never raises `ZeroDivisionError` even if that invariant is ever
  violated by a future change.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.plugins.registry import register_population_policy
from gov_platform.population_engine.base import (
    PopulationGroupCount,
    PopulationPolicy,
    PopulationWindow,
)
from gov_platform.population_engine.policies._shared import group_by_attribute
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome

_Z_CRITICAL = 2.0  # Castaneda v. Partida, 430 U.S. 482 (1977): "two or three standard deviations"
_MINIMUM_GROUP_SIZE = 30  # shared convention with AdverseImpactRatioPolicy
_STRUCTURAL_MINIMUM_GROUP_SIZE = 2  # hard floor: "compare at least two groups" (§13.16)
_MINIMUM_EXPECTED_CELL_COUNT = 5  # standard rule of thumb for the normal approximation's validity


def _resolve_parameters(parameters: dict[str, float]) -> tuple[float, int, list[str]]:
    """Resolves this policy's effective `(z_critical, minimum_group_size)`
    from a binding's `parameters`, mirroring `adverse_impact_ratio.py`'s
    `_resolve_parameters` shape (not shared — see `_shared.py`'s own
    docstring for why only grouping is shared between these two
    policies)."""
    notices: list[str] = []

    z_critical = parameters.get("z_critical", _Z_CRITICAL)
    if not math.isfinite(z_critical) or z_critical <= 0:
        notices.append(
            f"ignored out-of-range z_critical override {z_critical!r} "
            f"(must be > 0); using default {_Z_CRITICAL}"
        )
        z_critical = _Z_CRITICAL

    minimum_group_size_raw = parameters.get("minimum_group_size", float(_MINIMUM_GROUP_SIZE))
    if not math.isfinite(minimum_group_size_raw) or minimum_group_size_raw < 1:
        notices.append(
            f"ignored out-of-range minimum_group_size override {minimum_group_size_raw!r} "
            f"(must be >= 1); using default {_MINIMUM_GROUP_SIZE}"
        )
        minimum_group_size = _MINIMUM_GROUP_SIZE
    else:
        minimum_group_size = int(minimum_group_size_raw)

    minimum_group_size = max(minimum_group_size, _STRUCTURAL_MINIMUM_GROUP_SIZE)

    return z_critical, minimum_group_size, notices


def _is_eligible(group: PopulationGroupCount, *, minimum_group_size: int) -> bool:
    unfavorable_count = group.total_count - group.favorable_outcome_count
    return (
        group.total_count >= minimum_group_size
        and group.favorable_outcome_count >= _MINIMUM_EXPECTED_CELL_COUNT
        and unfavorable_count >= _MINIMUM_EXPECTED_CELL_COUNT
    )


def _two_proportion_z(group: PopulationGroupCount, reference: PopulationGroupCount) -> float | None:
    """The pooled-proportion two-proportion z-statistic comparing
    `group`'s favorable-outcome rate to `reference`'s. Returns `None` for
    a degenerate (zero-variance) comparison rather than raising -- see
    this module's docstring; unreachable in practice once both groups
    have already passed `_is_eligible`, kept as explicit defense in depth
    rather than relied upon implicitly."""
    n1, x1 = group.total_count, group.favorable_outcome_count
    n2, x2 = reference.total_count, reference.favorable_outcome_count
    pooled_p = (x1 + x2) / (n1 + n2)
    if pooled_p <= 0 or pooled_p >= 1:
        return None
    standard_error = math.sqrt(pooled_p * (1 - pooled_p) * (1 / n1 + 1 / n2))
    if standard_error == 0:  # pragma: no cover -- mathematically unreachable once
        # pooled_p is strictly between 0 and 1 (the only way past the check
        # above) and n1, n2 are both positive; kept as defense in depth, not
        # exercised by any realistic input.
        return None
    return (x1 / n1 - x2 / n2) / standard_error


@register_population_policy
class DisparitySignificanceTestPolicy(PopulationPolicy):
    """Flags a window when any `DIRECT`-classified protected attribute's
    value shows a favorable-outcome rate whose two-proportion z-statistic
    against the highest-rate value for that same attribute meets or
    exceeds `z_critical` in magnitude, among values with sufficient raw
    sample size and expected cell counts for the comparison to be valid."""

    population_policy_id = "disparity-significance-test"
    version = "0.1.0"

    def evaluate(self, window: PopulationWindow) -> PopulationFinding:
        z_critical, minimum_group_size, notices = _resolve_parameters(window.parameters)
        by_attribute = group_by_attribute(window.group_counts)

        metric_values: dict[str, float] = {}
        flagged_details: list[str] = []
        insufficient_attributes: list[str] = []
        any_z_computed = False

        for attribute_name in sorted(by_attribute):
            eligible = [
                g
                for g in by_attribute[attribute_name]
                if _is_eligible(g, minimum_group_size=minimum_group_size)
            ]
            if len(eligible) < 2:
                insufficient_attributes.append(attribute_name)
                continue

            reference_group = max(eligible, key=lambda g: g.favorable_outcome_count / g.total_count)
            any_z_computed_for_attribute = False
            for group in sorted(eligible, key=lambda g: g.attribute_value):
                if group.attribute_value == reference_group.attribute_value:
                    continue
                z = _two_proportion_z(group, reference_group)
                if z is None:
                    continue
                any_z_computed = True
                any_z_computed_for_attribute = True
                metric_values[f"{attribute_name}:{group.attribute_value}"] = z
                if abs(z) >= z_critical:
                    flagged_details.append(
                        f"{attribute_name}={group.attribute_value} disparity z-statistic "
                        f"{z:.3f} meets or exceeds the {z_critical} critical value"
                    )

            if not any_z_computed_for_attribute:
                insufficient_attributes.append(attribute_name)

        if flagged_details:
            outcome = PopulationFindingOutcome.FLAGGED
            rationale = "; ".join(flagged_details)
        elif any_z_computed:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = (
                "no protected-attribute value's disparity z-statistic reached the "
                f"{z_critical} critical value"
            )
        else:
            outcome = PopulationFindingOutcome.CLEAR
            rationale = "insufficient data to compute a disparity-significance test for this window"
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
                "z_critical": z_critical,
                "minimum_group_size": float(minimum_group_size),
            },
            rationale=rationale,
            evaluated_at=datetime.now(UTC),
        )
