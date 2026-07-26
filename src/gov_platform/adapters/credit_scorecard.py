"""The M2 real (non-synthetic) adapter — a classical-ML credit scorecard.

Models a realistic scorecard system's decision output: a `model_score`
computed from a `feature_vector`, compared against a `decision_threshold`
to produce `approved`, with `reason_codes` a real scorecard emits for
adverse-action notices. `demographic_indicators` are supplied separately
from `feature_vector` — a common real-world pattern where the scoring
model itself never sees protected characteristics, but a separate
compliance process attaches them post-hoc for fair-lending monitoring.

That separation is exactly what `DirectAttributeInInputsPolicy`
(`policy_engine/policies/direct_attribute_in_inputs.py`) checks stays
intact: if a direct protected characteristic (e.g. `race`) ever ends up
inside `feature_vector` instead of staying confined to
`demographic_indicators`, that's the real compliance failure this
milestone's policy exists to catch.

Field names are deliberately unlike `SyntheticSourcePayload`'s
(`decision_id` not `source_event_id`, `feature_vector` not `features`,
`demographic_indicators` not `protected_attributes`, `scored_at` not
`occurred_at`) — this is a second, independently-shaped wire format, not
a renamed copy of the first, which is the actual thing this milestone
needs to prove about the `Adapter[TPayload]` port.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from gov_platform.adapters.base import Adapter
from gov_platform.plugins.registry import register_adapter
from gov_platform.schemas.decision_event import DecisionEvent


class CreditScorecardPayload(BaseModel):
    """The wire shape a classical-ML credit scorecard system sends."""

    decision_id: str = Field(..., min_length=1, description="The scorecard's own decision id.")
    applicant_id: str = Field(..., min_length=1)
    system_name: str = Field(..., min_length=1)
    scored_at: datetime

    feature_vector: dict[str, float] = Field(default_factory=dict)
    demographic_indicators: dict[str, str] = Field(default_factory=dict)

    model_score: float
    decision_threshold: float
    approved: bool
    reason_codes: list[str] = Field(default_factory=list)


@register_adapter
class CreditScorecardAdapter(Adapter[CreditScorecardPayload]):
    """The second, real `Adapter` implementation — not a stand-in for a
    live external integration (there is none to connect to yet), but a
    genuinely different, realistically-shaped wire format, proving
    `Adapter[TPayload]`'s port generalizes beyond `SyntheticAdapter`, the
    one case it was built and tested against through M0/M1.

    `governing_policy_id="direct-attribute-in-inputs"`: retrofitted into
    the M3 registry unchanged from its M2 pairing.
    """

    adapter_id = "credit-scorecard"
    version = "0.1.0"
    governing_policy_id = "direct-attribute-in-inputs"

    def translate(self, raw_payload: CreditScorecardPayload) -> DecisionEvent:
        return DecisionEvent(
            event_id=raw_payload.decision_id,
            system_id=raw_payload.system_name,
            decision_type="credit_decision",
            subject_ref=raw_payload.applicant_id,
            occurred_at=raw_payload.scored_at,
            ingested_at=datetime.now(UTC),
            input_features=raw_payload.feature_vector,
            protected_attribute_refs=raw_payload.demographic_indicators,
            decision_output={
                "approved": raw_payload.approved,
                "model_score": raw_payload.model_score,
                "decision_threshold": raw_payload.decision_threshold,
                "reason_codes": raw_payload.reason_codes,
            },
        )
