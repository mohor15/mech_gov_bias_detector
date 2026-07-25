"""Structural normalization of an already-translated `DecisionEvent`.

M0 scope is intentionally thin: whitespace/timezone/precision normalization
only. Protected-attribute resolution (direct / proxied / withheld), business
context enrichment (jurisdiction, risk tier), and cross-adapter field
reconciliation are all M2+ concerns (architecture §4.3) — this service does
not reach into those fields at all yet.
"""

from __future__ import annotations

from datetime import UTC

from gov_platform.schemas.decision_event import DecisionEvent

_FEATURE_PRECISION = 4


class NormalizationService:
    """Applies structural normalization and returns a new `DecisionEvent`.

    Never mutates its input: `DecisionEvent` is frozen, and normalization
    that silently mutated evidence in place would undermine the reproducibility
    guarantee (architecture P9) the platform exists to provide.
    """

    def normalize(self, event: DecisionEvent) -> DecisionEvent:
        normalized_features = {
            key: round(value, _FEATURE_PRECISION) for key, value in event.input_features.items()
        }

        return event.model_copy(
            update={
                "system_id": event.system_id.strip(),
                "subject_ref": event.subject_ref.strip(),
                "input_features": normalized_features,
                "occurred_at": event.occurred_at.astimezone(UTC),
                "ingested_at": event.ingested_at.astimezone(UTC),
            }
        )
