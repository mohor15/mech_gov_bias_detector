from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.db.models import SystemRow
from gov_platform.schemas.system import System


class SystemRepository:
    def get(self, session: Session, system_id: str) -> System | None:
        row = session.get(SystemRow, system_id)
        return self._to_model(row) if row is not None else None

    def get_by_name(self, session: Session, name: str) -> System | None:
        row = session.execute(select(SystemRow).where(SystemRow.name == name)).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def create(
        self,
        session: Session,
        *,
        name: str,
        domain: str | None = None,
        risk_tier: str | None = None,
        owner: str | None = None,
    ) -> System:
        row = SystemRow(
            id=str(uuid4()),
            name=name,
            domain=domain,
            risk_tier=risk_tier,
            owner=owner,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return self._to_model(row)

    def get_or_create_by_name(self, session: Session, name: str) -> System:
        """Auto-provisioning path used by ingestion (see M1 design note:
        System registration is additive, not a precondition for ingestion).
        """
        existing = self.get_by_name(session, name)
        if existing is not None:
            return existing
        return self.create(session, name=name)

    def list(self, session: Session) -> list[System]:
        rows = session.execute(select(SystemRow).order_by(SystemRow.created_at)).scalars()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: SystemRow) -> System:
        return System(
            id=row.id,
            name=row.name,
            domain=row.domain,
            risk_tier=row.risk_tier,
            owner=row.owner,
            created_at=row.created_at,
        )
