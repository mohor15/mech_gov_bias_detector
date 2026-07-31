"""Repository for M5's Policy Bindings — architecture §7/§8.

Mirrors `PluginRegistrationRepository`'s shape (`create`, `get`,
`get_by_identity`, `list_all`), with `list_active_for_adapter` as the one
method `api/ingestion/routes.py`'s per-request policy resolution actually
depends on.

M14: `get_active_by_identity` is a new, additional method, not a change
to `get_by_identity`'s own existing, lifecycle-blind semantics --
`plugins/seed_registry.py`'s `seed_policy_binding` depends on that
existing meaning unchanged for its own idempotent-seed check. Mirrors
`PopulationPolicyBindingRepository.get_active_by_identity` (M8) exactly
-- see `docs/milestones/M14.md` §5.1/§13.20. `set_lifecycle_state` is now
a single conditional `UPDATE ... WHERE id = :id AND lifecycle_state !=
:target`, not a `session.get()`-then-mutate two-step -- closing
`docs/milestones/M9.md` §9.6's own named, pre-existing race, mirroring
`VerdictReviewRepository.claim`/`release`/`resolve` (M9) and
`PrincipalRepository.revoke` (M13)'s already-established pattern. See
`docs/milestones/M14.md` §5.2/§12.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
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
        partial unique index `one_active_policy_binding_per_adapter`
        (migration `0029`, M14; a plain `UNIQUE (adapter_id, policy_id)`
        constraint from migration `0011` before it) is what actually
        prevents a second `ACTIVE` binding for the same pair; this just
        makes the failure mode a clean `ValueError` instead of a raw
        `IntegrityError`."""
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
        """Lifecycle-blind: finds a binding for `(adapter_id, policy_id)`
        regardless of whether it's `ACTIVE` or `INACTIVE`. Depended on
        with exactly this meaning elsewhere (`plugins/seed_registry.py`'s
        idempotent-seed check) -- callers that specifically need "is
        there a currently-*active* binding for this key" (the
        create-endpoint's conflict check) must use
        `get_active_by_identity` instead, not this method."""
        row = session.execute(
            select(PolicyBindingRow).where(
                PolicyBindingRow.adapter_id == adapter_id,
                PolicyBindingRow.policy_id == policy_id,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def get_active_by_identity(
        self, session: Session, *, adapter_id: str, policy_id: str
    ) -> PolicyBinding | None:
        """Like `get_by_identity`, additionally scoped to
        `lifecycle_state == ACTIVE` -- `None` if the only binding(s) for
        this key are all deactivated, even though `get_by_identity` would
        still find one. Mirrors
        `PopulationPolicyBindingRepository.get_active_by_identity` (M8)
        exactly. See `docs/milestones/M14.md` §5.1."""
        row = session.execute(
            select(PolicyBindingRow).where(
                PolicyBindingRow.adapter_id == adapter_id,
                PolicyBindingRow.policy_id == policy_id,
                PolicyBindingRow.lifecycle_state == PolicyBindingLifecycleState.ACTIVE.value,
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
        """A single conditional `UPDATE ... WHERE id = :id AND
        lifecycle_state != :target`, checked by row count -- not a
        `session.get()`-then-mutate two-step, the same materially
        stronger concurrency-safety pattern `VerdictReviewRepository.claim`/
        `release`/`resolve` (M9) and `PrincipalRepository.revoke` (M13)
        already establish, closing `docs/milestones/M9.md` §9.6's own
        named, pre-existing race. A binding already in the requested
        state raises `ValueError`, the same "conflict, never a silent
        no-op" treatment every other conditional-`UPDATE` method in this
        codebase gives that case -- see `docs/milestones/M14.md` §12.1."""
        statement = (
            update(PolicyBindingRow)
            .where(
                PolicyBindingRow.id == binding_id,
                PolicyBindingRow.lifecycle_state != lifecycle_state.value,
            )
            .values(lifecycle_state=lifecycle_state.value)
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            row = session.get(PolicyBindingRow, binding_id, populate_existing=True)
            if row is None:
                raise ValueError(f"no policy binding with id {binding_id!r}")
            raise ValueError(f"policy binding {binding_id!r} is already {lifecycle_state.value}")
        session.flush()
        row = session.get(PolicyBindingRow, binding_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
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
