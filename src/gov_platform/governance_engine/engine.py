"""The Governance Engine orchestrator (architecture §8) — M0 skeleton.

Takes exactly one `Policy`, not a collection: the M0 milestone card scopes
this to "wrap a single Finding into a Verdict." A `list[Policy]` parameter
of length 1 would just be M4's multi-policy aggregation surface built early
and left unused — the constructor signature changes in M4, deliberately,
when there is a second policy and real aggregation logic to justify it.

Equally deliberately absent here: Policy Bindings (which policy applies to
which domain/jurisdiction), escalation rules, and verdict signing. Those
require concepts — bindings, an approval workflow, a key-management
integration — that do not exist yet. See `schemas.verdict.VerdictStatus`
for the corresponding two-state placeholder this engine populates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus


class GovernanceEngine:
    """Runs one `Policy` against one `DecisionEvent` and wraps the result."""

    def __init__(self, policy: Policy) -> None:
        self._policy = policy

    def govern(self, event: DecisionEvent) -> GovernanceVerdict:
        finding = self._policy.evaluate(event)
        is_clear = finding.outcome is FindingOutcome.CLEAR
        status = VerdictStatus.ALLOW if is_clear else VerdictStatus.FLAGGED

        return GovernanceVerdict(
            verdict_id=str(uuid4()),
            decision_event_id=event.event_id,
            status=status,
            findings=[finding],
            created_at=datetime.now(UTC),
        )
