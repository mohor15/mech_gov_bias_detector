from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import FindingRow, VerdictFindingRow, VerdictRow
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus


class VerdictRepository:
    def __init__(self, finding_repository: FindingRepository | None = None) -> None:
        self._finding_repository = finding_repository or FindingRepository()

    def create(self, session: Session, verdict: GovernanceVerdict) -> None:
        row = VerdictRow(
            id=verdict.verdict_id,
            decision_event_id=verdict.decision_event_id,
            status=verdict.status.value,
            created_at=verdict.created_at,
        )
        session.add(row)
        session.flush()

        for finding in verdict.findings:
            join_row = VerdictFindingRow(
                verdict_id=verdict.verdict_id, finding_id=finding.finding_id
            )
            session.add(join_row)
        session.flush()

    def get(self, session: Session, verdict_id: str) -> GovernanceVerdict | None:
        row = session.get(VerdictRow, verdict_id)
        if row is None:
            return None

        finding_rows = session.execute(
            select(FindingRow)
            .join(VerdictFindingRow, VerdictFindingRow.finding_id == FindingRow.id)
            .where(VerdictFindingRow.verdict_id == verdict_id)
            .order_by(FindingRow.evaluated_at)
        ).scalars()
        findings = [self._finding_repository.to_model(finding_row) for finding_row in finding_rows]

        return GovernanceVerdict(
            verdict_id=row.id,
            decision_event_id=row.decision_event_id,
            status=VerdictStatus(row.status),
            findings=findings,
            created_at=row.created_at,
        )
