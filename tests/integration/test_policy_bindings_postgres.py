"""`PolicyBindingRepository` — real Postgres round trip, including the
`UNIQUE (adapter_id, policy_id)` database constraint (migration `0011`).
CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.schemas.policy_binding import PolicyBindingLifecycleState, PolicySeverity
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _unique_adapter_id() -> str:
    return f"test-adapter-{uuid4()}"


def test_create_registers_a_new_binding_as_active(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        binding = PolicyBindingRepository().create(
            session,
            adapter_id=_unique_adapter_id(),
            policy_id="always-allow",
            severity=PolicySeverity.LOW,
        )

    assert binding.lifecycle_state is PolicyBindingLifecycleState.ACTIVE
    assert binding.severity is PolicySeverity.LOW


def test_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert PolicyBindingRepository().get(session, "no-such-id") is None


def test_get_by_identity_returns_none_for_an_unbound_pair(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = PolicyBindingRepository().get_by_identity(
            session, adapter_id="does-not-exist", policy_id="does-not-exist"
        )
    assert result is None


def test_get_by_identity_finds_a_created_binding(db_engine: Engine) -> None:
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        created = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        session.commit()

        found = repository.get_by_identity(session, adapter_id=adapter_id, policy_id="always-allow")

    assert found is not None
    assert found.id == created.id


def test_list_active_for_adapter_excludes_inactive_bindings(db_engine: Engine) -> None:
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        active = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        inactive = repository.create(
            session,
            adapter_id=adapter_id,
            policy_id="direct-attribute-in-inputs",
            severity=PolicySeverity.HIGH,
        )
        repository.set_lifecycle_state(session, inactive.id, PolicyBindingLifecycleState.INACTIVE)
        session.commit()

        bindings = repository.list_active_for_adapter(session, adapter_id)

    assert [b.id for b in bindings] == [active.id]


def test_list_active_for_adapter_returns_empty_for_an_unbound_adapter(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert PolicyBindingRepository().list_active_for_adapter(session, "no-such-adapter") == []


def test_set_lifecycle_state_toggles_active_and_inactive(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        binding = repository.create(
            session,
            adapter_id=_unique_adapter_id(),
            policy_id="always-allow",
            severity=PolicySeverity.LOW,
        )
        session.commit()

        deactivated = repository.set_lifecycle_state(
            session, binding.id, PolicyBindingLifecycleState.INACTIVE
        )
        assert deactivated.lifecycle_state is PolicyBindingLifecycleState.INACTIVE

        reactivated = repository.set_lifecycle_state(
            session, binding.id, PolicyBindingLifecycleState.ACTIVE
        )
        assert reactivated.lifecycle_state is PolicyBindingLifecycleState.ACTIVE


def test_set_lifecycle_state_on_an_unknown_binding_raises(db_engine: Engine) -> None:
    with (
        Session(db_engine) as session,
        pytest.raises(ValueError, match="no policy binding"),
    ):
        PolicyBindingRepository().set_lifecycle_state(
            session, "no-such-id", PolicyBindingLifecycleState.INACTIVE
        )


def test_create_raises_a_clean_error_for_a_duplicate_identity(db_engine: Engine) -> None:
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        session.commit()

        with pytest.raises(ValueError, match="already exists"):
            repository.create(
                session,
                adapter_id=adapter_id,
                policy_id="always-allow",
                severity=PolicySeverity.HIGH,
            )


def test_list_all_includes_created_bindings(db_engine: Engine) -> None:
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        created = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        session.commit()

        all_bindings = repository.list_all(session)

    assert created.id in {b.id for b in all_bindings}
