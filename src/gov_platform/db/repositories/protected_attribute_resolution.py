from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import ProtectedAttributeResolutionRow
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)


class ProtectedAttributeResolutionRepository:
    """Persists `ProtectedAttributeResolver`'s output.

    `ResolvedProtectedAttribute` is a value object with no identity of its
    own (unlike `Finding`/`Verdict`, which carry their own id from the
    domain layer) — this repository generates the row's primary key at
    persistence time, the same role `ModelVersionRepository.create` plays
    for `ModelVersion`.
    """

    def create(self, session: Session, resolution: ResolvedProtectedAttribute) -> None:
        row = ProtectedAttributeResolutionRow(
            id=str(uuid4()),
            decision_event_id=resolution.decision_event_id,
            attribute_name=resolution.attribute_name,
            classification=resolution.classification.value,
            proxy_basis=resolution.proxy_basis,
            resolved_at=resolution.resolved_at,
        )
        session.add(row)
        session.flush()

    def list_by_decision_event(
        self, session: Session, decision_event_id: str
    ) -> list[ResolvedProtectedAttribute]:
        statement = (
            select(ProtectedAttributeResolutionRow)
            .where(ProtectedAttributeResolutionRow.decision_event_id == decision_event_id)
            .order_by(ProtectedAttributeResolutionRow.attribute_name)
        )
        rows = session.execute(statement).scalars()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: ProtectedAttributeResolutionRow) -> ResolvedProtectedAttribute:
        return ResolvedProtectedAttribute(
            decision_event_id=row.decision_event_id,
            attribute_name=row.attribute_name,
            classification=ProtectedAttributeClassification(row.classification),
            proxy_basis=row.proxy_basis,
            resolved_at=row.resolved_at,
        )
