"""Reference adapter used by the M0 walking skeleton and its tests.

`SyntheticSourcePayload` deliberately uses different field names than the
canonical `DecisionEvent` (``source_event_id`` vs ``event_id``,
``features`` vs ``input_features``, etc.) so that `SyntheticAdapter.translate`
performs genuine field-level translation rather than being a no-op alias —
proving the adapter seam actually does something, which is the point of a
walking skeleton.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from gov_platform.adapters.base import Adapter
from gov_platform.plugins.registry import register_adapter
from gov_platform.schemas.decision_event import DecisionEvent


class SyntheticSourcePayload(BaseModel):
    """The wire shape a hypothetical synthetic source system sends."""

    source_event_id: str = Field(..., min_length=1)
    source_system: str = Field(..., min_length=1)
    decision_type: str = Field(..., min_length=1)
    subject_reference: str = Field(..., min_length=1)
    occurred_at: datetime

    features: dict[str, float] = Field(default_factory=dict)
    protected_attributes: dict[str, str] = Field(default_factory=dict)
    decision: dict[str, object] = Field(default_factory=dict)


@register_adapter
class SyntheticAdapter(Adapter[SyntheticSourcePayload]):
    """Reference `Adapter` implementation — not a stand-in for a real
    integration. A real classical-ML scorecard adapter arrived in M2.

    `governing_policy_ids=("always-allow",)`: the synthetic path carries
    no fairness-relevant protected attributes worth gating on (see
    `AlwaysAllowPolicy`'s own docstring) — a single-element tuple, since
    only one policy family has ever governed this path. Mechanical M4
    update (`str` -> `tuple[str, ...]`), no behavior change and no
    version bump: the actual governing policy set is identical.
    """

    adapter_id = "synthetic"
    version = "0.1.0"
    governing_policy_ids = ("always-allow",)

    def translate(self, raw_payload: SyntheticSourcePayload) -> DecisionEvent:
        return DecisionEvent(
            event_id=raw_payload.source_event_id,
            system_id=raw_payload.source_system,
            decision_type=raw_payload.decision_type,
            subject_ref=raw_payload.subject_reference,
            occurred_at=raw_payload.occurred_at,
            ingested_at=datetime.now(UTC),
            input_features=raw_payload.features,
            protected_attribute_refs=raw_payload.protected_attributes,
            decision_output=raw_payload.decision,
        )
