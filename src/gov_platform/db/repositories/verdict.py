from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import FindingRow, VerdictFindingRow, VerdictRow
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.schemas.finding import Finding
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
            # M4: policy_id is a secondary sort key so read order is
            # guaranteed to reproduce write order even if two policies in
            # the same GovernanceEngine.govern() call land on the same
            # evaluated_at timestamp (low clock resolution) -- see
            # docs/milestones/M4.md §13.7.
            .order_by(FindingRow.evaluated_at, FindingRow.policy_id)
        ).scalars()
        findings = [self._finding_repository.to_model(finding_row) for finding_row in finding_rows]

        return GovernanceVerdict(
            verdict_id=row.id,
            decision_event_id=row.decision_event_id,
            status=VerdictStatus(row.status),
            findings=findings,
            created_at=row.created_at,
        )

    def get_many(
        self, session: Session, verdict_ids: Sequence[str]
    ) -> dict[str, GovernanceVerdict]:
        """Batch equivalent of `get` — M9's Verdict Reviews Admin API
        (`api/admin/verdict_reviews.py`) is the first caller that needs
        more than one `Verdict`, embedded, per request; a per-id loop
        calling `get()` would be an N+1 query pattern the review-list
        endpoint's read pattern doesn't need to accept (found during M9's
        own hostile-review pass — see `docs/milestones/M9.md` §3.7/§7).
        Two queries total regardless of how many ids are requested, not
        two per id. Missing ids are simply absent from the returned dict.
        """
        if not verdict_ids:
            return {}

        verdict_rows = session.execute(
            select(VerdictRow).where(VerdictRow.id.in_(verdict_ids))
        ).scalars()
        verdict_rows_by_id = {row.id: row for row in verdict_rows}

        finding_rows = session.execute(
            select(FindingRow, VerdictFindingRow.verdict_id)
            .join(VerdictFindingRow, VerdictFindingRow.finding_id == FindingRow.id)
            .where(VerdictFindingRow.verdict_id.in_(verdict_ids))
            # Same secondary sort key as `get()`, for the same reason —
            # see that method's own comment.
            .order_by(FindingRow.evaluated_at, FindingRow.policy_id)
        ).all()
        findings_by_verdict_id: dict[str, list[Finding]] = defaultdict(list)
        for finding_row, verdict_id in finding_rows:
            findings_by_verdict_id[verdict_id].append(
                self._finding_repository.to_model(finding_row)
            )

        return {
            verdict_id: GovernanceVerdict(
                verdict_id=row.id,
                decision_event_id=row.decision_event_id,
                status=VerdictStatus(row.status),
                findings=findings_by_verdict_id[verdict_id],
                created_at=row.created_at,
            )
            for verdict_id, row in verdict_rows_by_id.items()
        }
