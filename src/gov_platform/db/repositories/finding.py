from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import FindingRow
from gov_platform.schemas.finding import Finding, FindingOutcome


class FindingRepository:
    def create(self, session: Session, finding: Finding) -> None:
        row = FindingRow(
            id=finding.finding_id,
            decision_event_id=finding.decision_event_id,
            policy_id=finding.policy_id,
            policy_version=finding.policy_version,
            outcome=finding.outcome.value,
            confidence=finding.confidence,
            rationale=finding.rationale,
            metric_values=json.dumps(finding.metric_values),
            evaluated_at=finding.evaluated_at,
        )
        session.add(row)
        session.flush()

    def list_by_decision_event(self, session: Session, decision_event_id: str) -> list[Finding]:
        statement = (
            select(FindingRow)
            .where(FindingRow.decision_event_id == decision_event_id)
            .order_by(FindingRow.evaluated_at)
        )
        rows = session.execute(statement).scalars()
        return [self.to_model(row) for row in rows]

    @staticmethod
    def to_model(row: FindingRow) -> Finding:
        """Public: `VerdictRepository` reuses this to reconstruct a
        verdict's findings via the `verdict_findings` join, rather than
        duplicating the FindingRow -> Finding mapping in two places."""
        return Finding(
            finding_id=row.id,
            decision_event_id=row.decision_event_id,
            policy_id=row.policy_id,
            policy_version=row.policy_version,
            outcome=FindingOutcome(row.outcome),
            confidence=row.confidence,
            rationale=row.rationale,
            metric_values=json.loads(row.metric_values),
            evaluated_at=row.evaluated_at,
        )
