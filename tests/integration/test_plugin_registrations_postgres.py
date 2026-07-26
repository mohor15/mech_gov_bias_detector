"""`PluginRegistrationRepository` — real Postgres round trip, including
the one-PRODUCTION-per-plugin database constraint (migration `0010`).
CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import PluginRegistrationRow
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _unique_plugin_id() -> str:
    return f"test-plugin-{uuid4()}"


def test_create_registers_a_new_plugin_as_draft(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        registration = PluginRegistrationRepository().create(
            session, plugin_type=PluginType.POLICY, plugin_id=_unique_plugin_id(), version="1.0.0"
        )

    assert registration.lifecycle_state is PluginLifecycleState.DRAFT
    assert registration.promoted_at is None


def test_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert PluginRegistrationRepository().get(session, "no-such-id") is None


def test_get_by_identity_returns_none_for_an_unregistered_plugin(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = PluginRegistrationRepository().get_by_identity(
            session, plugin_type=PluginType.ADAPTER, plugin_id="does-not-exist", version="0.0.0"
        )
    assert result is None


def test_list_by_type_and_plugin_id_returns_every_version(db_engine: Engine) -> None:
    plugin_id = _unique_plugin_id()
    with Session(db_engine) as session:
        repository = PluginRegistrationRepository()
        repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="1.0.0"
        )
        repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="2.0.0"
        )
        session.commit()

        registrations = repository.list_by_type_and_plugin_id(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id
        )

    assert {r.version for r in registrations} == {"1.0.0", "2.0.0"}


def test_promote_advances_one_stage_at_a_time(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        repository = PluginRegistrationRepository()
        registration = repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=_unique_plugin_id(), version="1.0.0"
        )
        session.commit()

        registration = repository.promote(session, registration.id)
        assert registration.lifecycle_state is PluginLifecycleState.SHADOW

        registration = repository.promote(session, registration.id)
        assert registration.lifecycle_state is PluginLifecycleState.PRODUCTION
        assert registration.promoted_at is not None


def test_promoting_a_second_version_to_production_demotes_the_first_to_shadow(
    db_engine: Engine,
) -> None:
    plugin_id = _unique_plugin_id()
    with Session(db_engine) as session:
        repository = PluginRegistrationRepository()
        v1 = repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="1.0.0"
        )
        v2 = repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="2.0.0"
        )
        session.commit()

        v1 = repository.promote(session, v1.id)
        v1 = repository.promote(session, v1.id)  # DRAFT -> SHADOW -> PRODUCTION
        session.commit()
        assert v1.lifecycle_state is PluginLifecycleState.PRODUCTION

        v2 = repository.promote(session, v2.id)
        v2 = repository.promote(session, v2.id)  # DRAFT -> SHADOW -> PRODUCTION
        session.commit()

        v1_after = repository.get(session, v1.id)

    assert v2.lifecycle_state is PluginLifecycleState.PRODUCTION
    assert v1_after is not None
    assert v1_after.lifecycle_state is PluginLifecycleState.SHADOW


def test_promoting_an_already_production_registration_raises(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        repository = PluginRegistrationRepository()
        registration = repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=_unique_plugin_id(), version="1.0.0"
        )
        registration = repository.promote(session, registration.id)
        registration = repository.promote(session, registration.id)
        session.commit()

        with pytest.raises(ValueError, match="already PRODUCTION"):
            repository.promote(session, registration.id)


def test_promoting_an_unknown_registration_raises(db_engine: Engine) -> None:
    with (
        Session(db_engine) as session,
        pytest.raises(ValueError, match="no plugin registration"),
    ):
        PluginRegistrationRepository().promote(session, "no-such-id")


def test_create_raises_a_clean_error_for_a_duplicate_identity(db_engine: Engine) -> None:
    # Production-readiness finding: the Admin API's check-then-insert has
    # a real race window under concurrent callers (two requests
    # registering the identical identity at once could both pass the
    # "not already registered" check). The UNIQUE constraint (migration
    # 0010) is the actual guarantee; this proves create() surfaces that
    # as a clean ValueError, not a raw IntegrityError -- exercised here by
    # simply calling create() twice, which hits the exact same code path
    # a genuine race would.
    plugin_id = _unique_plugin_id()
    with Session(db_engine) as session:
        repository = PluginRegistrationRepository()
        repository.create(
            session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="1.0.0"
        )
        session.commit()

        with pytest.raises(ValueError, match="already registered"):
            repository.create(
                session, plugin_type=PluginType.POLICY, plugin_id=plugin_id, version="1.0.0"
            )


def test_database_rejects_two_production_versions_for_the_same_plugin_inserted_directly(
    db_engine: Engine,
) -> None:
    # Bypasses the repository's own promote() ordering entirely, proving
    # the actual guarantee is the database constraint (migration 0010),
    # not just the repository's application-level discipline -- the same
    # standard M1's evidence-immutability work was held to.
    plugin_id = _unique_plugin_id()
    with Session(db_engine) as session:
        session.add(
            PluginRegistrationRow(
                id=str(uuid4()),
                plugin_type=PluginType.POLICY.value,
                plugin_id=plugin_id,
                version="1.0.0",
                lifecycle_state=PluginLifecycleState.PRODUCTION.value,
                registered_at=datetime.now(UTC),
            )
        )
        session.commit()

        session.add(
            PluginRegistrationRow(
                id=str(uuid4()),
                plugin_type=PluginType.POLICY.value,
                plugin_id=plugin_id,
                version="2.0.0",
                lifecycle_state=PluginLifecycleState.PRODUCTION.value,
                registered_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
