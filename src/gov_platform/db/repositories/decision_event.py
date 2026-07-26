from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import DecisionEventRow, ModelVersionRow, SystemRow
from gov_platform.schemas.decision_event import DecisionEvent


class DecisionEventRepository:
    """Persists the normalized operational copy of a Decision Event.

    `decision_events.id` is `DecisionEvent.event_id` and is the table's
    primary key — a new, deliberate uniqueness constraint M0's blob table
    never enforced (see M1 design note). Ingesting the same event_id twice
    raises an `IntegrityError`, not a silent duplicate.

    The row stores `model_version_id`, not `system_id` directly (correct
    normalization — a System can have several ModelVersions). `get`
    reconstructs the full domain object via a join back to `systems.name`,
    since `DecisionEvent.system_id` is a required field on the domain model.
    """

    def create(self, session: Session, event: DecisionEvent, *, model_version_id: str) -> None:
        row = DecisionEventRow(
            id=event.event_id,
            model_version_id=model_version_id,
            decision_type=event.decision_type,
            subject_ref=event.subject_ref,
            occurred_at=event.occurred_at,
            ingested_at=event.ingested_at,
            input_features=json.dumps(event.input_features),
            protected_attribute_refs=json.dumps(event.protected_attribute_refs),
            decision_output=json.dumps(event.decision_output, default=str),
        )
        session.add(row)
        session.flush()

    def get(self, session: Session, event_id: str) -> DecisionEvent | None:
        result = session.execute(
            select(DecisionEventRow, SystemRow.name)
            .join(ModelVersionRow, DecisionEventRow.model_version_id == ModelVersionRow.id)
            .join(SystemRow, ModelVersionRow.system_id == SystemRow.id)
            .where(DecisionEventRow.id == event_id)
        ).one_or_none()
        if result is None:
            return None
        row, system_name = result
        return DecisionEvent(
            event_id=row.id,
            system_id=system_name,
            decision_type=row.decision_type,
            subject_ref=row.subject_ref,
            occurred_at=row.occurred_at,
            ingested_at=row.ingested_at,
            input_features=json.loads(row.input_features),
            protected_attribute_refs=json.loads(row.protected_attribute_refs),
            decision_output=json.loads(row.decision_output),
        )
