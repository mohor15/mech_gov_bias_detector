"""`PopulationPolicyBindingRepository` — real Postgres round trip, including
the `UNIQUE (system_id, population_policy_id)` database constraint
(migration `0014`) and the `system_id` foreign key. CI-only (see
conftest.requires_postgres). Mirrors `test_policy_bindings_postgres.py`'s
shape.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_policy_binding import PopulationPolicyBindingLifecycleState
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _new_system_id(db_engine) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"test-system-{uuid4()}")
        session.commit()
    return system.id


def test_create_registers_a_new_binding_as_active(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        binding = PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )

    assert binding.lifecycle_state is PopulationPolicyBindingLifecycleState.ACTIVE
    assert binding.system_id == system_id


def test_create_for_a_nonexistent_system_raises(db_engine) -> None:
    with (
        Session(db_engine) as session,
        pytest.raises(ValueError, match="already exists|does not exist"),
    ):
        PopulationPolicyBindingRepository().create(
            session, system_id="no-such-system", population_policy_id="adverse-impact-ratio"
        )


def test_get_returns_none_for_an_unknown_id(db_engine) -> None:
    with Session(db_engine) as session:
        assert PopulationPolicyBindingRepository().get(session, "no-such-id") is None


def test_get_by_identity_finds_a_created_binding(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        created = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        found = repository.get_by_identity(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )

    assert found is not None
    assert found.id == created.id


def test_get_by_identity_returns_none_for_an_unbound_pair(db_engine) -> None:
    with Session(db_engine) as session:
        result = PopulationPolicyBindingRepository().get_by_identity(
            session, system_id="does-not-exist", population_policy_id="does-not-exist"
        )
    assert result is None


def test_create_raises_a_clean_error_for_a_duplicate_identity(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        repository.create(session, system_id=system_id, population_policy_id="adverse-impact-ratio")
        session.commit()

        with pytest.raises(ValueError, match="already exists"):
            repository.create(
                session, system_id=system_id, population_policy_id="adverse-impact-ratio"
            )


def test_list_active_for_system_excludes_inactive_bindings(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        active = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        inactive = repository.create(
            session, system_id=system_id, population_policy_id="some-other-policy"
        )
        repository.set_lifecycle_state(
            session, inactive.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

        bindings = repository.list_active_for_system(session, system_id)

    assert [b.id for b in bindings] == [active.id]


def test_list_active_returns_every_active_binding_across_systems(db_engine) -> None:
    system_a = _new_system_id(db_engine)
    system_b = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        a = repository.create(
            session, system_id=system_a, population_policy_id="adverse-impact-ratio"
        )
        b = repository.create(
            session, system_id=system_b, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        active_ids = {binding.id for binding in repository.list_active(session)}

    assert {a.id, b.id} <= active_ids


def test_set_lifecycle_state_toggles_active_and_inactive(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        binding = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        deactivated = repository.set_lifecycle_state(
            session, binding.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        assert deactivated.lifecycle_state is PopulationPolicyBindingLifecycleState.INACTIVE

        reactivated = repository.set_lifecycle_state(
            session, binding.id, PopulationPolicyBindingLifecycleState.ACTIVE
        )
        assert reactivated.lifecycle_state is PopulationPolicyBindingLifecycleState.ACTIVE


def test_set_lifecycle_state_on_an_unknown_binding_raises(db_engine) -> None:
    with (
        Session(db_engine) as session,
        pytest.raises(ValueError, match="no population policy binding"),
    ):
        PopulationPolicyBindingRepository().set_lifecycle_state(
            session, "no-such-id", PopulationPolicyBindingLifecycleState.INACTIVE
        )


def test_set_lifecycle_state_on_a_binding_already_in_the_requested_state_raises(
    db_engine,
) -> None:
    """M14 §12.1 option (a): a redundant transition is a conflict, never a
    silent no-op -- the same treatment `VerdictReviewRepository.claim`/
    `PrincipalRepository.revoke` give an already-claimed/already-revoked
    row (`docs/milestones/M14.md` §5.2/§12.1/§12.2)."""
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        binding = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        with pytest.raises(ValueError, match="already"):
            repository.set_lifecycle_state(
                session, binding.id, PopulationPolicyBindingLifecycleState.ACTIVE
            )


# --- M8: admin-configurable parameters and the relaxed uniqueness
# constraint (docs/milestones/M8.md §4.3/§4.4) ---


def test_create_with_no_parameters_persists_and_reads_back_an_empty_dict(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        binding = PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )

    assert binding.parameters == {}


def test_create_with_parameters_persists_and_reads_back(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        created = repository.create(
            session,
            system_id=system_id,
            population_policy_id="adverse-impact-ratio",
            parameters={"threshold": 0.75},
        )
        session.commit()

        fetched = repository.get(session, created.id)

    assert created.parameters == {"threshold": 0.75}
    assert fetched is not None
    assert fetched.parameters == {"threshold": 0.75}


def test_get_active_by_identity_finds_an_active_binding(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        created = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        found = repository.get_active_by_identity(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )

    assert found is not None
    assert found.id == created.id


def test_get_active_by_identity_returns_none_for_a_deactivated_binding(db_engine) -> None:
    """The hostile-review-pass finding (§13.19): `get_by_identity` still
    finds a deactivated binding, but `get_active_by_identity` must not --
    this is the exact distinction the Admin API's conflict check depends
    on to make recreation possible."""
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        created = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        repository.set_lifecycle_state(
            session, created.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

        active = repository.get_active_by_identity(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        lifecycle_blind = repository.get_by_identity(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )

    assert active is None
    assert lifecycle_blind is not None
    assert lifecycle_blind.id == created.id


def test_a_new_binding_can_be_created_after_the_old_one_is_deactivated(db_engine) -> None:
    """The end-to-end proof migration `0022`'s relaxed constraint plus
    `get_active_by_identity` together make possible (docs/milestones/M8.md
    §4.4/§13.19) -- at the repository layer. The equivalent proof through
    the Admin API itself lives in
    test_admin_population_policy_bindings_api.py, since the repository
    was never the layer the original bug lived in."""
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        original = repository.create(
            session,
            system_id=system_id,
            population_policy_id="adverse-impact-ratio",
            parameters={"threshold": 0.8},
        )
        repository.set_lifecycle_state(
            session, original.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

        replacement = repository.create(
            session,
            system_id=system_id,
            population_policy_id="adverse-impact-ratio",
            parameters={"threshold": 0.7},
        )
        session.commit()

    assert replacement.id != original.id
    assert replacement.parameters == {"threshold": 0.7}
    assert replacement.lifecycle_state is PopulationPolicyBindingLifecycleState.ACTIVE


def test_list_all_includes_created_bindings(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        created = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

        all_bindings = repository.list_all(session)

    assert created.id in {b.id for b in all_bindings}
