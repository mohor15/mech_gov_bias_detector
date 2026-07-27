"""Canonical Protected Attribute Rule — architecture §4.3, M5.

Dynamic, admin-managed replacement for
`protected_attributes/classification.py`'s static `_RULES_BY_DOMAIN` dict.
Consumed by `EvidenceStore`'s resolution path only — see
`docs/milestones/M5.md` §13.9 for why `DirectAttributeInInputsPolicy`
deliberately keeps reading the static, in-code ruleset instead.

A distinct enum from `ProtectedAttributeClassification`
(`schemas/protected_attribute.py`), not a reuse: `WITHHELD` describes an
event-time *absence*, which has no meaning for a *rule* row — a rule only
ever says an attribute is `DIRECT` or a `PROXY`, never "withheld".
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProtectedAttributeRuleClassification(StrEnum):
    DIRECT = "DIRECT"
    PROXY = "PROXY"


class ProtectedAttributeRule(BaseModel):
    """One domain's classification rule for one attribute name."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    attribute_name: str = Field(..., min_length=1)
    classification: ProtectedAttributeRuleClassification
    proxy_of: str | None = Field(
        default=None,
        description="Which direct attribute this proxies. Set iff classification is PROXY.",
    )
    created_at: datetime
