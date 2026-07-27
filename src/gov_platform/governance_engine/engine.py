"""The Governance Engine orchestrator (architecture §8) — M5: escalation.

M4 aggregated N policies via any-`FLAGGED`-wins into a two-state
`VerdictStatus` placeholder, explicitly deferring "which of three non-ALLOW
states applies" to this milestone (`docs/milestones/M4.md` §13.3). M5
answers that question using `PolicySeverity`, which now travels alongside
each `Policy` as a `GoverningPolicy` — severity lives on the binding that
associates a policy with an adapter (`schemas/policy_binding.py`), not on
`Policy` itself, so `GovernanceEngine` needs both, bundled, per policy it
runs. See `docs/milestones/M5.md` §13.5 for the full reasoning and §9 for
this constructor's design.

Aggregation rule: the *highest* severity among all flagged findings decides
the verdict's status ("most restrictive wins" — the same principle M4 used
for its binary OR, extended to three tiers). An all-`CLEAR` verdict is
always `ALLOW`. This is a static, three-tier mapping, not a pluggable rule
engine — there is exactly one aggregation rule and no second one to justify
an abstraction, the same reasoning M4 §13.3 already applied. See
`docs/milestones/M5.md` §13.6.

Failure semantics are unchanged from M4: if any policy raises, this method
does not catch it — the exception propagates to the caller (the ingestion
route), which fails the whole request rather than aggregating from a
partial finding set.

Findings are built in the exact order `governing_policies` was constructed
with — deterministic and free, since evaluation is sequential. See
`db/repositories/verdict.py`'s secondary sort key for why this matters on
the read side too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import FindingOutcome
from gov_platform.schemas.policy_binding import PolicySeverity
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus

_SEVERITY_TO_STATUS: dict[PolicySeverity, VerdictStatus] = {
    PolicySeverity.LOW: VerdictStatus.ALLOW_WITH_FLAG,
    PolicySeverity.MEDIUM: VerdictStatus.ESCALATE_FOR_REVIEW,
    PolicySeverity.HIGH: VerdictStatus.RECOMMEND_HOLD,
}

# Ranks PolicySeverity for `max()` -- StrEnum members compare by string
# value, not by governance meaning, so "HIGH" > "LOW" alphabetically would
# be an accident, not a guarantee. This is the one place that ordering is
# spelled out explicitly.
_SEVERITY_RANK: dict[PolicySeverity, int] = {
    PolicySeverity.LOW: 0,
    PolicySeverity.MEDIUM: 1,
    PolicySeverity.HIGH: 2,
}


@dataclass(frozen=True)
class GoverningPolicy:
    """One `Policy` bundled with the severity its binding assigns it — the
    unit `GovernanceEngine` needs per policy now that severity, not just
    whether a policy flags at all, determines the verdict's status."""

    policy: Policy
    severity: PolicySeverity


class GovernanceEngine:
    """Runs every `Policy` it was constructed with against one
    `DecisionEvent` and aggregates their Findings into one Verdict."""

    def __init__(self, governing_policies: list[GoverningPolicy]) -> None:
        if not governing_policies:
            raise ValueError("GovernanceEngine requires at least one GoverningPolicy")
        self._governing_policies = governing_policies

    def govern(self, event: DecisionEvent) -> GovernanceVerdict:
        findings = [gp.policy.evaluate(event) for gp in self._governing_policies]
        flagged_severities = [
            gp.severity
            for gp, finding in zip(self._governing_policies, findings, strict=True)
            if finding.outcome is FindingOutcome.FLAGGED
        ]
        status = (
            _SEVERITY_TO_STATUS[max(flagged_severities, key=_SEVERITY_RANK.__getitem__)]
            if flagged_severities
            else VerdictStatus.ALLOW
        )

        return GovernanceVerdict(
            verdict_id=str(uuid4()),
            decision_event_id=event.event_id,
            status=status,
            findings=findings,
            created_at=datetime.now(UTC),
        )
