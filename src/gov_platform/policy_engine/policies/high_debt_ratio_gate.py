"""The M4 second reference policy — architecture §7.

Deliberately **not** another fairness/protected-attribute check.
`DirectAttributeInInputsPolicy` (M2) already proves that kind of judgment;
this milestone's actual job is proving `GovernanceEngine` aggregates
genuinely *different kinds* of judgment for the same adapter (a fairness
gate and a plain risk gate), not two variations on the same theme — see
`docs/milestones/M4.md` §13.10.

Revives the spirit of `legacy_v1`'s debt-to-income check, called out in
this codebase's own history as "V1's dead-code DTI check" that M2's
policy was meant to eventually replace (it built the fairness gate
instead). This is that replacement, built as real, tested logic instead
of the V1 prototype's inert placeholder.

The 0.43 threshold is the CFPB's Ability-to-Repay/Qualified Mortgage rule
debt-to-income limit (12 CFR § 1026.43(e)(2)(vi)) — a real, commonly-cited
regulatory reference point, not an arbitrary round number. It is still
illustrative for this platform (chosen to give the example concrete,
checkable provenance), not a claim that this deployment is bound by that
specific regulation. See `docs/milestones/M4.md`'s production-readiness
review on why a hardcoded threshold is a real governance smell worth
naming explicitly rather than hiding.

An event that doesn't supply `debt_to_income` at all is `CLEAR`, not
`FLAGGED`: this policy has no signal to evaluate, and inventing risk from
an absent feature would be a different (and considerably more aggressive)
policy than "flag high debt-to-income," which is the one this milestone
is scoped to build.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.plugins.registry import register_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome

_DEBT_TO_INCOME_FEATURE = "debt_to_income"
_MAX_DEBT_TO_INCOME = 0.43  # CFPB ATR/QM rule, 12 CFR § 1026.43(e)(2)(vi)


@register_policy
class HighDebtRatioGatePolicy(Policy):
    """Flags a Decision Event whose `debt_to_income` input feature exceeds
    `_MAX_DEBT_TO_INCOME`."""

    policy_id = "high-debt-ratio-gate"
    version = "0.1.0"

    def evaluate(self, event: DecisionEvent) -> Finding:
        debt_to_income = event.input_features.get(_DEBT_TO_INCOME_FEATURE)

        if debt_to_income is None or debt_to_income <= _MAX_DEBT_TO_INCOME:
            return Finding(
                finding_id=str(uuid4()),
                decision_event_id=event.event_id,
                policy_id=self.policy_id,
                policy_version=self.version,
                outcome=FindingOutcome.CLEAR,
                confidence=1.0,
                rationale=(
                    "debt_to_income not supplied"
                    if debt_to_income is None
                    else f"debt_to_income {debt_to_income} is within the "
                    f"{_MAX_DEBT_TO_INCOME} limit"
                ),
                metric_values={} if debt_to_income is None else {"debt_to_income": debt_to_income},
                evaluated_at=datetime.now(UTC),
            )

        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.FLAGGED,
            confidence=1.0,
            rationale=(f"debt_to_income {debt_to_income} exceeds the {_MAX_DEBT_TO_INCOME} limit"),
            metric_values={"debt_to_income": debt_to_income},
            evaluated_at=datetime.now(UTC),
        )
