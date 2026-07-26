"""Canonical Protected Attribute Resolution — architecture §4.3, M2.

Output of the Protected Attribute Resolution Service: for each attribute a
domain expects to see on a `DecisionEvent`, whether it was supplied
directly, supplied via a known proxy, or withheld (not supplied at all).

Deliberately a separate model, not a new field on `DecisionEvent`.
`DecisionEvent` stays frozen and unaware it has been resolved — see
`protected_attributes/resolver.py`'s module docstring for why this
sidesteps the raw/normalized/resolved pipeline-stage-type question M0
explicitly deferred rather than resolving it in favor of new types.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProtectedAttributeClassification(StrEnum):
    """How one expected protected attribute relates to a Decision Event.

    ``WITHHELD`` means *absence*: the domain expects this attribute to be
    resolvable and the event didn't carry it — not a platform-side
    redaction of an attribute it did receive. See
    `protected_attributes/classification.py` for the expected-attribute
    lists this depends on.
    """

    DIRECT = "DIRECT"
    PROXIED = "PROXIED"
    WITHHELD = "WITHHELD"


class ResolvedProtectedAttribute(BaseModel):
    """One (Decision Event, expected attribute) resolution."""

    model_config = ConfigDict(frozen=True)

    decision_event_id: str = Field(..., min_length=1)
    attribute_name: str = Field(..., min_length=1)
    classification: ProtectedAttributeClassification
    proxy_basis: str | None = Field(
        default=None,
        description="Which direct attribute this proxies, if classification is PROXIED.",
    )
    resolved_at: datetime
