"""Repository for the M3 plugin-lifecycle registry — architecture §6.

`promote` is the interesting method: it advances exactly one lifecycle
stage (`DRAFT` -> `SHADOW` -> `PRODUCTION`) and, when promoting into
`PRODUCTION`, demotes whatever previously held that slot for the same
`(plugin_type, plugin_id)` to `SHADOW` — not `DRAFT` — so the
just-replaced version stays observable for continued comparison rather
than going silent (see `docs/milestones/M3.md`'s design review).

The demotion is flushed to the database *before* the promotion, as two
separate statements, not one combined flush: Postgres checks the
`one_production_version_per_plugin` partial unique index (migration
`0010`) at the end of each statement, not deferred to the end of the
transaction, so promoting first would (however briefly, within the same
transaction) put two rows in `PRODUCTION` at once and violate it. This
repository also checks the invariant itself for a clean error message —
but the database constraint is the actual guarantee, per
`docs/milestones/M3.md` §13.6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import PluginRegistrationRow
from gov_platform.schemas.plugin_registration import (
    PluginLifecycleState,
    PluginRegistration,
    PluginType,
)

_NEXT_STATE: dict[PluginLifecycleState, PluginLifecycleState] = {
    PluginLifecycleState.DRAFT: PluginLifecycleState.SHADOW,
    PluginLifecycleState.SHADOW: PluginLifecycleState.PRODUCTION,
}


class PluginRegistrationRepository:
    def create(
        self, session: Session, *, plugin_type: PluginType, plugin_id: str, version: str
    ) -> PluginRegistration:
        """Production-readiness note: callers (the Admin API, `seed_registry`)
        check `get_by_identity` first, but that check-then-insert has a real
        race window under concurrent callers — two requests registering the
        identical identity at once could both pass the check. The database's
        own `UNIQUE (plugin_type, plugin_id, version)` constraint (migration
        `0010`) is what actually prevents the duplicate; this just makes the
        failure mode a clean `ValueError` instead of a raw `IntegrityError`
        surfacing as an unhandled 500."""
        row = PluginRegistrationRow(
            id=str(uuid4()),
            plugin_type=plugin_type.value,
            plugin_id=plugin_id,
            version=version,
            lifecycle_state=PluginLifecycleState.DRAFT.value,
            registered_at=datetime.now(UTC),
            promoted_at=None,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"{plugin_type.value} {plugin_id!r} version {version!r} is already registered"
            ) from exc
        return self._to_model(row)

    def get(self, session: Session, registration_id: str) -> PluginRegistration | None:
        row = session.get(PluginRegistrationRow, registration_id)
        return self._to_model(row) if row is not None else None

    def get_by_identity(
        self, session: Session, *, plugin_type: PluginType, plugin_id: str, version: str
    ) -> PluginRegistration | None:
        row = session.execute(
            select(PluginRegistrationRow).where(
                PluginRegistrationRow.plugin_type == plugin_type.value,
                PluginRegistrationRow.plugin_id == plugin_id,
                PluginRegistrationRow.version == version,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def list_all(self, session: Session) -> list[PluginRegistration]:
        # Named list_all, not list: a method literally named `list` shadows
        # the builtin `list` type within this class body's own namespace
        # under postponed annotation evaluation (`from __future__ import
        # annotations`), breaking `list[...]` return annotations on any
        # method defined after it. SystemRepository has a `list` method
        # too, but only ever gets away with it because it happens to be
        # the last method before a staticmethod with no `list[...]` of its
        # own -- not a safe pattern to repeat.
        rows = session.execute(
            select(PluginRegistrationRow).order_by(PluginRegistrationRow.registered_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_by_type_and_plugin_id(
        self, session: Session, *, plugin_type: PluginType, plugin_id: str
    ) -> list[PluginRegistration]:
        rows = session.execute(
            select(PluginRegistrationRow).where(
                PluginRegistrationRow.plugin_type == plugin_type.value,
                PluginRegistrationRow.plugin_id == plugin_id,
            )
        ).scalars()
        return [self._to_model(row) for row in rows]

    def promote(self, session: Session, registration_id: str) -> PluginRegistration:
        """Advance one lifecycle stage. Raises `ValueError` (mapped to a
        422 at the API boundary, same as `ProtectedAttributeResolver`'s
        errors) if the registration doesn't exist or is already
        `PRODUCTION` — there is nothing further to promote to."""
        row = session.get(PluginRegistrationRow, registration_id)
        if row is None:
            raise ValueError(f"no plugin registration with id {registration_id!r}")

        current_state = PluginLifecycleState(row.lifecycle_state)
        next_state = _NEXT_STATE.get(current_state)
        if next_state is None:
            raise ValueError(
                f"registration {registration_id!r} is already PRODUCTION -- nothing to promote to"
            )

        if next_state is PluginLifecycleState.PRODUCTION:
            previous_production = session.execute(
                select(PluginRegistrationRow).where(
                    PluginRegistrationRow.plugin_type == row.plugin_type,
                    PluginRegistrationRow.plugin_id == row.plugin_id,
                    PluginRegistrationRow.lifecycle_state == PluginLifecycleState.PRODUCTION.value,
                )
            ).scalar_one_or_none()
            if previous_production is not None:
                previous_production.lifecycle_state = PluginLifecycleState.SHADOW.value
                previous_production.promoted_at = datetime.now(UTC)
                # Flushed separately, before `row` is promoted below --
                # see this module's docstring for why the order matters.
                session.flush()

        row.lifecycle_state = next_state.value
        row.promoted_at = datetime.now(UTC)
        try:
            session.flush()
        except IntegrityError as exc:  # pragma: no cover
            # Same race as create()'s: a concurrent promotion to PRODUCTION
            # for the same plugin_id could slip past the "previous_production"
            # check above and hit the one_production_version_per_plugin
            # index. The index is the real guarantee; this is just the
            # clean-error translation.
            #
            # Not covered by a test: attempted with a real two-thread
            # test and found genuinely flaky, not because the race can't
            # happen, but because there are two *correct* outcomes
            # depending on actual timing (both promotions can legitimately
            # succeed sequentially, each correctly demoting the other's
            # predecessor, if the OS never truly interleaves their writes)
            # -- forcing and asserting one specific outcome produced a
            # test that failed under the very conditions it was meant to
            # prove safe. create()'s equivalent branch (same pattern, one
            # unambiguous outcome) is tested directly instead.
            session.rollback()
            raise ValueError(
                f"registration {registration_id!r} could not be promoted -- another "
                "registration was promoted to PRODUCTION for the same plugin concurrently"
            ) from exc
        return self._to_model(row)

    @staticmethod
    def _to_model(row: PluginRegistrationRow) -> PluginRegistration:
        return PluginRegistration(
            id=row.id,
            plugin_type=PluginType(row.plugin_type),
            plugin_id=row.plugin_id,
            version=row.version,
            lifecycle_state=PluginLifecycleState(row.lifecycle_state),
            registered_at=row.registered_at,
            promoted_at=row.promoted_at,
        )
