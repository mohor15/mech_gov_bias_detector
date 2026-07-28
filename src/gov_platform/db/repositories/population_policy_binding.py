"""Repository for M6's Population Policy Bindings — architecture §7/§8.

Mirrors `PolicyBindingRepository`'s shape (`create`, `get`,
`get_by_identity`, `list_all`, `set_lifecycle_state`), with
`list_active_for_system` as the one method
`population_engine/run_policies.py`'s batch run actually depends on —
the direct analogue of `list_active_for_adapter` for the ingestion route.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import PopulationPolicyBindingRow
from gov_platform.schemas.population_policy_binding import (
    PopulationPolicyBinding,
    PopulationPolicyBindingLifecycleState,
)


class PopulationPolicyBindingRepository:
    def create(
        self, session: Session, *, system_id: str, population_policy_id: str
    ) -> PopulationPolicyBinding:
        """Production-readiness note: same check-then-insert race every
        other repository in this codebase documents -- the database's
        `UNIQUE (system_id, population_policy_id)` constraint (migration
        `0014`) is what actually prevents a duplicate; this just makes the
        failure mode a clean `ValueError` instead of a raw `IntegrityError`.
        `system_id` must reference an existing `systems` row -- enforced by
        the table's own foreign key, surfacing as the same `IntegrityError`
        path if it doesn't."""
        row = PopulationPolicyBindingRow(
            id=str(uuid4()),
            system_id=system_id,
            population_policy_id=population_policy_id,
            lifecycle_state=PopulationPolicyBindingLifecycleState.ACTIVE.value,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"a population policy binding for system {system_id!r} -> population policy "
                f"{population_policy_id!r} already exists, or system {system_id!r} does not exist"
            ) from exc
        return self._to_model(row)

    def get(self, session: Session, binding_id: str) -> PopulationPolicyBinding | None:
        row = session.get(PopulationPolicyBindingRow, binding_id)
        return self._to_model(row) if row is not None else None

    def get_by_identity(
        self, session: Session, *, system_id: str, population_policy_id: str
    ) -> PopulationPolicyBinding | None:
        row = session.execute(
            select(PopulationPolicyBindingRow).where(
                PopulationPolicyBindingRow.system_id == system_id,
                PopulationPolicyBindingRow.population_policy_id == population_policy_id,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def list_all(self, session: Session) -> list[PopulationPolicyBinding]:
        rows = session.execute(
            select(PopulationPolicyBindingRow).order_by(PopulationPolicyBindingRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_active_for_system(
        self, session: Session, system_id: str
    ) -> list[PopulationPolicyBinding]:
        """Mirrors `PolicyBindingRepository.list_active_for_adapter`'s
        shape for one system."""
        rows = session.execute(
            select(PopulationPolicyBindingRow)
            .where(
                PopulationPolicyBindingRow.system_id == system_id,
                PopulationPolicyBindingRow.lifecycle_state
                == PopulationPolicyBindingLifecycleState.ACTIVE.value,
            )
            .order_by(PopulationPolicyBindingRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_active(self, session: Session) -> list[PopulationPolicyBinding]:
        """Every `ACTIVE` binding across every system, in `created_at`
        order -- deterministic, the set `population_engine/run_policies.py`'s
        batch run actually iterates (one run evaluates every bound system,
        not one)."""
        rows = session.execute(
            select(PopulationPolicyBindingRow)
            .where(
                PopulationPolicyBindingRow.lifecycle_state
                == PopulationPolicyBindingLifecycleState.ACTIVE.value
            )
            .order_by(PopulationPolicyBindingRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def set_lifecycle_state(
        self,
        session: Session,
        binding_id: str,
        lifecycle_state: PopulationPolicyBindingLifecycleState,
    ) -> PopulationPolicyBinding:
        row = session.get(PopulationPolicyBindingRow, binding_id)
        if row is None:
            raise ValueError(f"no population policy binding with id {binding_id!r}")
        row.lifecycle_state = lifecycle_state.value
        session.flush()
        return self._to_model(row)

    @staticmethod
    def _to_model(row: PopulationPolicyBindingRow) -> PopulationPolicyBinding:
        return PopulationPolicyBinding(
            id=row.id,
            system_id=row.system_id,
            population_policy_id=row.population_policy_id,
            lifecycle_state=PopulationPolicyBindingLifecycleState(row.lifecycle_state),
            created_at=row.created_at,
        )
