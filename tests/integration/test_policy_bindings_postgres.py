"""`PolicyBindingRepository` — real Postgres round trip, including the
partial unique index scoped to `ACTIVE` (migration `0029`, M14 -- see
`docs/milestones/M14.md` §5.1/§5.2/§6). CI-only (see
conftest.requires_postgres).
"""

from __future__ import annotations

import threading
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


def test_get_active_by_identity_finds_an_active_binding(db_engine: Engine) -> None:
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        created = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        session.commit()

        found = repository.get_active_by_identity(
            session, adapter_id=adapter_id, policy_id="always-allow"
        )

    assert found is not None
    assert found.id == created.id


def test_get_active_by_identity_returns_none_for_a_deactivated_binding(db_engine: Engine) -> None:
    """The M8-era finding, applied here to `policy_bindings` (M14,
    `docs/milestones/M14.md` §5.1): `get_by_identity` still finds a
    deactivated binding, but `get_active_by_identity` must not -- this is
    the exact distinction the Admin API's conflict check depends on to
    make recreation possible."""
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        created = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        repository.set_lifecycle_state(session, created.id, PolicyBindingLifecycleState.INACTIVE)
        session.commit()

        active = repository.get_active_by_identity(
            session, adapter_id=adapter_id, policy_id="always-allow"
        )
        lifecycle_blind = repository.get_by_identity(
            session, adapter_id=adapter_id, policy_id="always-allow"
        )

    assert active is None
    assert lifecycle_blind is not None
    assert lifecycle_blind.id == created.id


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


def test_set_lifecycle_state_on_a_binding_already_in_the_requested_state_raises(
    db_engine: Engine,
) -> None:
    """M14 §12.1 option (a): a redundant transition is a conflict, never a
    silent no-op -- the same treatment `VerdictReviewRepository.claim`/
    `PrincipalRepository.revoke` give an already-claimed/already-revoked
    row (`docs/milestones/M14.md` §5.2/§12.1)."""
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        binding = repository.create(
            session,
            adapter_id=_unique_adapter_id(),
            policy_id="always-allow",
            severity=PolicySeverity.LOW,
        )
        session.commit()

        with pytest.raises(ValueError, match="already"):
            repository.set_lifecycle_state(session, binding.id, PolicyBindingLifecycleState.ACTIVE)


def test_the_set_lifecycle_state_race_directly(db_engine: Engine) -> None:
    """Exactly one of several concurrent `deactivate`-equivalent calls
    against the same `ACTIVE` binding succeeds; the rest observe
    zero-rows-affected and raise -- never both silently "succeeding" with
    the last write winning, closing `docs/milestones/M9.md` §9.6's own
    named race (`docs/milestones/M14.md` §1 item 2/§12.1, Revision note
    item 12). Mirrors `test_verdict_reviews_postgres.py`'s own
    `test_the_claim_race_directly` exactly."""
    repository = PolicyBindingRepository()
    with Session(db_engine) as session:
        binding = repository.create(
            session,
            adapter_id=_unique_adapter_id(),
            policy_id="always-allow",
            severity=PolicySeverity.LOW,
        )
        session.commit()

    results: list[str] = []
    lock = threading.Lock()

    def _try_deactivate() -> None:
        try:
            with Session(db_engine) as session:
                repository.set_lifecycle_state(
                    session, binding.id, PolicyBindingLifecycleState.INACTIVE
                )
                session.commit()
            outcome = "success"
        except ValueError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_try_deactivate) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("success") == 1
    assert results.count("conflict") == 9


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


def test_a_new_binding_can_be_created_after_the_old_one_is_deactivated(db_engine: Engine) -> None:
    """The end-to-end proof migration `0029`'s relaxed constraint plus
    `get_active_by_identity` together make possible
    (`docs/milestones/M14.md` §5.1/§6) -- at the repository layer. The
    equivalent proof through the Admin API itself lives in
    `test_admin_policy_bindings_api.py`, since the original bug (M8
    §13.20) lived entirely in that endpoint's own conflict check."""
    adapter_id = _unique_adapter_id()
    with Session(db_engine) as session:
        repository = PolicyBindingRepository()
        original = repository.create(
            session, adapter_id=adapter_id, policy_id="always-allow", severity=PolicySeverity.LOW
        )
        repository.set_lifecycle_state(session, original.id, PolicyBindingLifecycleState.INACTIVE)
        session.commit()

        replacement = repository.create(
            session,
            adapter_id=adapter_id,
            policy_id="always-allow",
            severity=PolicySeverity.HIGH,
        )
        session.commit()

    assert replacement.id != original.id
    assert replacement.severity is PolicySeverity.HIGH
    assert replacement.lifecycle_state is PolicyBindingLifecycleState.ACTIVE


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
