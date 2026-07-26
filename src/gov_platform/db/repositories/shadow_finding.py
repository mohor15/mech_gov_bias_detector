"""Repository for M3's shadow-Finding side channel — architecture §6.

Structurally separate from `FindingRepository`/`findings` (see
`db/models.ShadowFindingRow` and `docs/milestones/M3.md` §13.3): a shadow
policy's output can never be mistaken for one that actually contributed
to a served `Verdict`, because it lives in a different table entirely.
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import PluginRegistrationRow, ShadowFindingRow
from gov_platform.schemas.finding import Finding, FindingOutcome


class ShadowFindingRepository:
    def create(self, session: Session, finding: Finding, *, plugin_registration_id: str) -> None:
        row = ShadowFindingRow(
            id=str(uuid4()),
            decision_event_id=finding.decision_event_id,
            plugin_registration_id=plugin_registration_id,
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
            select(ShadowFindingRow, PluginRegistrationRow.plugin_id, PluginRegistrationRow.version)
            .join(
                PluginRegistrationRow,
                ShadowFindingRow.plugin_registration_id == PluginRegistrationRow.id,
            )
            .where(ShadowFindingRow.decision_event_id == decision_event_id)
            .order_by(ShadowFindingRow.evaluated_at)
        )
        results = session.execute(statement).all()
        return [
            self._to_model(row, policy_id=plugin_id, policy_version=version)
            for row, plugin_id, version in results
        ]

    @staticmethod
    def _to_model(row: ShadowFindingRow, *, policy_id: str, policy_version: str) -> Finding:
        return Finding(
            finding_id=row.id,
            decision_event_id=row.decision_event_id,
            policy_id=policy_id,
            policy_version=policy_version,
            outcome=FindingOutcome(row.outcome),
            confidence=row.confidence,
            rationale=row.rationale,
            metric_values=json.loads(row.metric_values),
            evaluated_at=row.evaluated_at,
        )
