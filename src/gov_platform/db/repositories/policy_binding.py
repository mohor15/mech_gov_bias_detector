"""Repository for M5's Policy Bindings — architecture §7/§8.

Mirrors `PluginRegistrationRepository`'s shape (`create`, `get`,
`get_by_identity`, `list_all`), with `list_active_for_adapter` as the one
method `api/ingestion/routes.py`'s per-request policy resolution actually
depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import PolicyBindingRow
from gov_platform.schemas.policy_binding import (
    PolicyBinding,
    PolicyBindingLifecycleState,
    PolicySeverity,
)


class PolicyBindingRepository:
    def create(
        self, session: Session, *, adapter_id: str, policy_id: str, severity: PolicySeverity
    ) -> PolicyBinding:
        """Production-readiness note: same check-then-insert race the
        plugin registry's own `create` documents -- the database's
        `UNIQUE (adapter_id, policy_id)` constraint (migration `0011`) is
        what actually prevents a duplicate; this just makes the failure
        mode a clean `ValueError` instead of a raw `IntegrityError`."""
        row = PolicyBindingRow(
            id=str(uuid4()),
            adapter_id=adapter_id,
            policy_id=policy_id,
            severity=severity.value,
            lifecycle_state=PolicyBindingLifecycleState.ACTIVE.value,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"a policy binding for adapter {adapter_id!r} -> policy {policy_id!r} "
                "already exists"
            ) from exc
        return self._to_model(row)

    def get(self, session: Session, binding_id: str) -> PolicyBinding | None:
        row = session.get(PolicyBindingRow, binding_id)
        return self._to_model(row) if row is not None else None

    def get_by_identity(
        self, session: Session, *, adapter_id: str, policy_id: str
    ) -> PolicyBinding | None:
        row = session.execute(
            select(PolicyBindingRow).where(
                PolicyBindingRow.adapter_id == adapter_id,
                PolicyBindingRow.policy_id == policy_id,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def list_all(self, session: Session) -> list[PolicyBinding]:
        rows = session.execute(
            select(PolicyBindingRow).order_by(PolicyBindingRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_active_for_adapter(self, session: Session, adapter_id: str) -> list[PolicyBinding]:
        """The set `api/ingestion/routes.py` resolves one `GoverningPolicy`
        from per binding, in `created_at` order -- deterministic, the same
        discipline M4 already applied to `governing_policy_ids` order."""
        rows = session.execute(
            select(PolicyBindingRow)
            .where(
                PolicyBindingRow.adapter_id == adapter_id,
                PolicyBindingRow.lifecycle_state == PolicyBindingLifecycleState.ACTIVE.value,
            )
            .order_by(PolicyBindingRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def set_lifecycle_state(
        self, session: Session, binding_id: str, lifecycle_state: PolicyBindingLifecycleState
    ) -> PolicyBinding:
        row = session.get(PolicyBindingRow, binding_id)
        if row is None:
            raise ValueError(f"no policy binding with id {binding_id!r}")
        row.lifecycle_state = lifecycle_state.value
        session.flush()
        return self._to_model(row)

    @staticmethod
    def _to_model(row: PolicyBindingRow) -> PolicyBinding:
        return PolicyBinding(
            id=row.id,
            adapter_id=row.adapter_id,
            policy_id=row.policy_id,
            severity=PolicySeverity(row.severity),
            lifecycle_state=PolicyBindingLifecycleState(row.lifecycle_state),
            created_at=row.created_at,
        )
