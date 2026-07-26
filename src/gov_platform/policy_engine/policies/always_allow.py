"""The M0 reference policy.

Exists to prove the `Policy` contract end to end, not to govern anything —
it unconditionally clears every event. The first policy with real judgment
(a rule-based hard gate, wired to genuine upstream metrics rather than
V1's dead-code DTI check) arrives in M2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.plugins.registry import register_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome


@register_policy
class AlwaysAllowPolicy(Policy):
    policy_id = "always-allow"
    version = "0.1.0"

    def evaluate(self, event: DecisionEvent) -> Finding:
        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="M0 reference policy: unconditionally clears every event.",
            metric_values={},
            evaluated_at=datetime.now(UTC),
        )
