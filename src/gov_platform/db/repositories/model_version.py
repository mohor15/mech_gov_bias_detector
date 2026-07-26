from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import ModelVersionRow
from gov_platform.schemas.model_version import ModelVersion


class ModelVersionRepository:
    def get(self, session: Session, model_version_id: str) -> ModelVersion | None:
        row = session.get(ModelVersionRow, model_version_id)
        return self._to_model(row) if row is not None else None

    def get_by_system_and_version(
        self, session: Session, system_id: str, version: str
    ) -> ModelVersion | None:
        row = session.execute(
            select(ModelVersionRow).where(
                ModelVersionRow.system_id == system_id,
                ModelVersionRow.version == version,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def create(self, session: Session, *, system_id: str, version: str) -> ModelVersion:
        row = ModelVersionRow(
            id=str(uuid4()),
            system_id=system_id,
            version=version,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return self._to_model(row)

    def get_or_create(self, session: Session, *, system_id: str, version: str) -> ModelVersion:
        existing = self.get_by_system_and_version(session, system_id, version)
        if existing is not None:
            return existing
        return self.create(session, system_id=system_id, version=version)

    def list_by_system(self, session: Session, system_id: str) -> list[ModelVersion]:
        statement = (
            select(ModelVersionRow)
            .where(ModelVersionRow.system_id == system_id)
            .order_by(ModelVersionRow.created_at)
        )
        rows = session.execute(statement).scalars()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: ModelVersionRow) -> ModelVersion:
        return ModelVersion(
            id=row.id, system_id=row.system_id, version=row.version, created_at=row.created_at
        )
