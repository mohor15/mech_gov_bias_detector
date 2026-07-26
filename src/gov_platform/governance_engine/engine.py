"""The Governance Engine orchestrator (architecture §8) — M4: policy plurality.

M0 through M3 ran exactly one `Policy`, deliberately: "a `list[Policy]`
parameter of length 1 would just be M4's multi-policy aggregation surface
built early and left unused." M4 is that surface, now that
`CreditScorecardAdapter` has two genuinely independent governing policies
(a fairness gate and a risk gate — see `policy_engine/policies/
high_debt_ratio_gate.py`) to justify it.

Aggregation rule: any `FLAGGED` finding makes the verdict `FLAGGED` — a
logical OR across all findings' outcomes ("most restrictive wins"). This
needs no new `VerdictStatus` values (still the two-state ALLOW/FLAGGED
placeholder; the full four-state model remains M5's job) and is not a
pluggable strategy — there is exactly one aggregation rule and no second
one to justify an abstraction, the same reasoning that kept
`ProtectedAttributeResolver` (M2) and the plugin registry (M3) concrete
classes rather than new ports. See `docs/milestones/M4.md` §13.3.

Failure semantics: if any policy raises, this method does not catch it —
the exception propagates to the caller (the ingestion route), which fails
the whole request rather than aggregating from a partial finding set. A
governance decision made on deliberately incomplete information is worse
than a clear failure. See `docs/milestones/M4.md` §13.5.

Findings are built in the exact order `policies` was constructed with —
deterministic and free, since evaluation is sequential. See
`db/repositories/verdict.py`'s secondary sort key for why this matters on
the read side too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus


class GovernanceEngine:
    """Runs every `Policy` it was constructed with against one
    `DecisionEvent` and aggregates their Findings into one Verdict."""

    def __init__(self, policies: list[Policy]) -> None:
        if not policies:
            raise ValueError("GovernanceEngine requires at least one Policy")
        self._policies = policies

    def govern(self, event: DecisionEvent) -> GovernanceVerdict:
        findings = [policy.evaluate(event) for policy in self._policies]
        any_flagged = any(finding.outcome is FindingOutcome.FLAGGED for finding in findings)
        status = VerdictStatus.FLAGGED if any_flagged else VerdictStatus.ALLOW

        return GovernanceVerdict(
            verdict_id=str(uuid4()),
            decision_event_id=event.event_id,
            status=status,
            findings=findings,
            created_at=datetime.now(UTC),
        )
