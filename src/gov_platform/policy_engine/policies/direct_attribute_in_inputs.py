"""The M2 reference judgment-bearing policy — architecture §7.

Flags a Decision Event when a `DIRECT`-classified protected attribute
(e.g. `race`) also appears as a key in the model's own `input_features`.
Many fair-lending regimes prohibit exactly this: a model must not use a
protected characteristic as a decision input, even when that same
characteristic is otherwise legitimately supplied for compliance
monitoring (see `adapters/credit_scorecard.py`'s module docstring for the
`feature_vector`/`demographic_indicators` separation this checks stays
intact).

Scope note: this checks attributes classified `DIRECT` (present in
`protected_attribute_refs`) against `input_features`. It deliberately
does not also check `WITHHELD` attributes (protected attributes the event
didn't disclose at all) against `input_features` — an undisclosed
protected attribute silently used as a model input is a real, distinct
risk, but detecting it requires consulting the domain's ruleset directly
rather than per-event resolutions, and is not solved by this milestone's
first version of this policy. Flagging as a known scope boundary, not an
oversight.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.policy_engine.base import Policy
from gov_platform.protected_attributes.classification import FINANCE_DOMAIN
from gov_platform.protected_attributes.resolver import ProtectedAttributeResolver
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.protected_attribute import ProtectedAttributeClassification


class DirectAttributeInInputsPolicy(Policy):
    """Fixed to the one domain `CreditScorecardAdapter` targets.

    `Policy.evaluate` receives only a `DecisionEvent` — the port's
    signature is unchanged this milestone (see `docs/milestones/M2.md`
    §7) — which carries no live database access and no `System` row, so
    this policy cannot look up `System.domain` dynamically the way
    `EvidenceStore` does. It is instead constructed for exactly the one
    domain it's deployed to govern, the same way `policy_id`/`version`
    are fixed identity, not runtime-derived.

    Holds a `ProtectedAttributeResolver` as a constructor collaborator —
    the same pattern `VerdictRepository` already uses for
    `FindingRepository` — rather than widening `Policy.evaluate`'s
    signature to accept resolution data directly. Widening a stable port
    ahead of a second policy that needs the same input would repeat the
    exact premature-generalization mistake `GovernanceEngine`'s
    single-`Policy` constructor has consistently avoided elsewhere.
    """

    policy_id = "direct-attribute-in-inputs"
    version = "0.1.0"

    def __init__(self, resolver: ProtectedAttributeResolver | None = None) -> None:
        self._resolver = resolver or ProtectedAttributeResolver()

    def evaluate(self, event: DecisionEvent) -> Finding:
        resolutions = self._resolver.resolve(event, domain=FINANCE_DOMAIN)
        direct_attributes_in_inputs = sorted(
            resolution.attribute_name
            for resolution in resolutions
            if resolution.classification is ProtectedAttributeClassification.DIRECT
            and resolution.attribute_name in event.input_features
        )

        if not direct_attributes_in_inputs:
            return Finding(
                finding_id=str(uuid4()),
                decision_event_id=event.event_id,
                policy_id=self.policy_id,
                policy_version=self.version,
                outcome=FindingOutcome.CLEAR,
                confidence=1.0,
                rationale="No direct protected attribute found in the model's input_features.",
                metric_values={"direct_attributes_in_inputs_count": 0.0},
                evaluated_at=datetime.now(UTC),
            )

        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.FLAGGED,
            confidence=1.0,
            rationale=(
                f"Direct protected attribute(s) {direct_attributes_in_inputs} found in "
                "the model's own input_features -- a protected characteristic must not "
                "be used as a decision input."
            ),
            metric_values={
                "direct_attributes_in_inputs_count": float(len(direct_attributes_in_inputs))
            },
            evaluated_at=datetime.now(UTC),
        )
