"""`PopulationFindingRepository` — real Postgres round trip, including the
`UNIQUE (population_policy_id, system_id, window_start, window_end)`
database constraint (migration `0015`) that makes a duplicate/overlapping
`run_policies` invocation a clean no-op — see
`docs/milestones/M6.md` §13.13. CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres

_WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 1, 2, tzinfo=UTC)


def _new_system_id(db_engine) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"test-system-{uuid4()}")
        session.commit()
    return system.id


def _finding(system_id: str, **overrides: object) -> PopulationFinding:
    defaults: dict[str, object] = {
        "population_finding_id": f"pf-{uuid4()}",
        "population_policy_id": "adverse-impact-ratio",
        "population_policy_version": "0.1.0",
        "system_id": system_id,
        "window_start": _WINDOW_START,
        "window_end": _WINDOW_END,
        "outcome": PopulationFindingOutcome.FLAGGED,
        "metric_values": {"race:Black": 0.75},
        "classification_snapshot": {"race": "DIRECT"},
        "rationale": "test rationale",
        "evaluated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PopulationFinding(**defaults)  # type: ignore[arg-type]


def test_create_persists_and_round_trips_every_field(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    finding = _finding(system_id)

    with Session(db_engine) as session:
        record = PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()

    assert record.id == finding.population_finding_id
    assert record.outcome is PopulationFindingOutcome.FLAGGED
    assert record.metric_values == {"race:Black": 0.75}
    assert record.classification_snapshot == {"race": "DIRECT"}
    assert record.signature == "deadbeef"
    assert record.signing_key_id == "default"


def test_get_returns_none_for_an_unknown_id(db_engine) -> None:
    with Session(db_engine) as session:
        assert PopulationFindingRepository().get(session, "no-such-id") is None


def test_get_returns_the_created_record(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    finding = _finding(system_id)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        repository.create(session, finding, signature=None, signing_key_id=None)
        session.commit()

        fetched = repository.get(session, finding.population_finding_id)

    assert fetched is not None
    assert fetched.id == finding.population_finding_id
    assert fetched.signature is None


def test_duplicate_window_for_the_same_policy_and_system_raises(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        repository.create(session, _finding(system_id), signature=None, signing_key_id=None)
        session.commit()

        with pytest.raises(ValueError, match="already exists"):
            repository.create(
                session,
                _finding(system_id, population_finding_id=f"pf-{uuid4()}"),
                signature=None,
                signing_key_id=None,
            )


def test_a_different_window_for_the_same_policy_and_system_is_allowed(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        repository.create(session, _finding(system_id), signature=None, signing_key_id=None)
        session.commit()

        second = repository.create(
            session,
            _finding(
                system_id,
                population_finding_id=f"pf-{uuid4()}",
                window_start=datetime(2026, 1, 2, tzinfo=UTC),
                window_end=datetime(2026, 1, 3, tzinfo=UTC),
            ),
            signature=None,
            signing_key_id=None,
        )
        session.commit()

    assert second is not None


def test_list_for_system_returns_only_that_systems_findings(db_engine) -> None:
    system_a = _new_system_id(db_engine)
    system_b = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        finding_a = repository.create(
            session, _finding(system_a), signature=None, signing_key_id=None
        )
        repository.create(session, _finding(system_b), signature=None, signing_key_id=None)
        session.commit()

        results = repository.list_for_system(session, system_a)

    assert [r.id for r in results] == [finding_a.id]


def test_list_all_includes_created_findings(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        created = repository.create(
            session, _finding(system_id), signature=None, signing_key_id=None
        )
        session.commit()

        all_findings = repository.list_all(session)

    assert created.id in {f.id for f in all_findings}


def test_parameters_used_defaults_to_none_and_round_trips_as_none(db_engine) -> None:
    """M8 (docs/milestones/M8.md §4.5/§13.18): a finding built without
    setting `parameters_used` (reproducing every pre-M8 record) must read
    back as `None`, not `{}` -- the exact distinction the signature
    hash-compatibility fix depends on."""
    system_id = _new_system_id(db_engine)
    finding = _finding(system_id)
    assert finding.parameters_used is None

    with Session(db_engine) as session:
        record = PopulationFindingRepository().create(
            session, finding, signature=None, signing_key_id=None
        )
        session.commit()

        fetched = PopulationFindingRepository().get(session, record.id)

    assert record.parameters_used is None
    assert fetched is not None
    assert fetched.parameters_used is None


def test_parameters_used_round_trips_a_real_dict(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    finding = _finding(system_id, parameters_used={"threshold": 0.75, "minimum_group_size": 30.0})

    with Session(db_engine) as session:
        record = PopulationFindingRepository().create(
            session, finding, signature=None, signing_key_id=None
        )
        session.commit()

        fetched = PopulationFindingRepository().get(session, record.id)

    assert record.parameters_used == {"threshold": 0.75, "minimum_group_size": 30.0}
    assert fetched is not None
    assert fetched.parameters_used == {"threshold": 0.75, "minimum_group_size": 30.0}


def test_list_all_respects_limit(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        for i in range(3):
            repository.create(
                session,
                _finding(
                    system_id,
                    population_finding_id=f"pf-{uuid4()}",
                    window_start=datetime(2026, 1, i + 1, tzinfo=UTC),
                    window_end=datetime(2026, 1, i + 2, tzinfo=UTC),
                    evaluated_at=datetime(2026, 1, i + 2, tzinfo=UTC),
                ),
                signature=None,
                signing_key_id=None,
            )
        session.commit()

        limited = repository.list_all(session, limit=2)

    assert len(limited) == 2


def test_list_all_respects_offset(db_engine) -> None:
    """`list_all` has no filter to scope this comparison to just the rows
    this test creates (unlike `list_for_system`, exercised separately
    below) -- `population_findings` is shared and never truncated across
    the whole test session, so this asserts the table-size-independent
    property `offset` actually guarantees (skip exactly the first N rows
    of the existing order, return the rest unchanged) rather than assuming
    this test's own rows are the table's very first."""
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        for i in range(3):
            repository.create(
                session,
                _finding(
                    system_id,
                    population_finding_id=f"pf-{uuid4()}",
                    window_start=datetime(2026, 1, i + 1, tzinfo=UTC),
                    window_end=datetime(2026, 1, i + 2, tzinfo=UTC),
                    evaluated_at=datetime(2026, 1, i + 2, tzinfo=UTC),
                ),
                signature=None,
                signing_key_id=None,
            )
        session.commit()

        full = repository.list_all(session)
        offset_by_one = repository.list_all(session, offset=1)

    assert len(offset_by_one) == len(full) - 1
    assert [r.id for r in offset_by_one] == [r.id for r in full[1:]]


def test_list_for_system_respects_limit_and_offset(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        for i in range(3):
            repository.create(
                session,
                _finding(
                    system_id,
                    population_finding_id=f"pf-{uuid4()}",
                    window_start=datetime(2026, 1, i + 1, tzinfo=UTC),
                    window_end=datetime(2026, 1, i + 2, tzinfo=UTC),
                    evaluated_at=datetime(2026, 1, i + 2, tzinfo=UTC),
                ),
                signature=None,
                signing_key_id=None,
            )
        session.commit()

        page = repository.list_for_system(session, system_id, limit=1, offset=1)

    assert len(page) == 1


def test_offset_without_limit_returns_everything_after_the_skipped_rows(db_engine) -> None:
    """M15 §5.1: `limit`/`offset` are independent -- `offset` alone is
    valid, ordinary SQL, not an error."""
    system_id = _new_system_id(db_engine)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        for i in range(3):
            repository.create(
                session,
                _finding(
                    system_id,
                    population_finding_id=f"pf-{uuid4()}",
                    window_start=datetime(2026, 1, i + 1, tzinfo=UTC),
                    window_end=datetime(2026, 1, i + 2, tzinfo=UTC),
                    evaluated_at=datetime(2026, 1, i + 2, tzinfo=UTC),
                ),
                signature=None,
                signing_key_id=None,
            )
        session.commit()

        all_for_system = repository.list_for_system(session, system_id)
        skipped = repository.list_for_system(session, system_id, offset=1)

    assert len(skipped) == len(all_for_system) - 1


def test_pagination_is_stable_when_two_findings_share_evaluated_at(db_engine) -> None:
    """M15 §5.2, mirroring `docs/milestones/M4.md` §13.7's own already-
    shipped fix: `evaluated_at` alone is not a unique sort key -- two
    findings from the same batch run can share it. Paging through with
    `limit=1` must visit every row exactly once, never duplicating or
    skipping one, proving the `id` secondary sort key actually closes the
    tie-break gap rather than merely documenting it."""
    system_id = _new_system_id(db_engine)
    shared_evaluated_at = datetime(2026, 6, 1, tzinfo=UTC)
    with Session(db_engine) as session:
        repository = PopulationFindingRepository()
        created = [
            repository.create(
                session,
                _finding(
                    system_id,
                    population_finding_id=f"pf-{uuid4()}",
                    population_policy_id=f"policy-{i}",
                    window_start=datetime(2026, 1, i + 1, tzinfo=UTC),
                    window_end=datetime(2026, 1, i + 2, tzinfo=UTC),
                    evaluated_at=shared_evaluated_at,
                ),
                signature=None,
                signing_key_id=None,
            )
            for i in range(4)
        ]
        session.commit()
        created_ids = {c.id for c in created}

        seen: list[str] = []
        offset = 0
        while True:
            page = repository.list_for_system(session, system_id, limit=1, offset=offset)
            if not page:
                break
            seen.append(page[0].id)
            offset += 1

    seen_for_this_system = [rid for rid in seen if rid in created_ids]
    assert len(seen_for_this_system) == len(created_ids)
    assert len(set(seen_for_this_system)) == len(created_ids)  # no duplicate, no skip


def test_as_population_finding_drops_signature_fields(db_engine) -> None:
    system_id = _new_system_id(db_engine)
    finding = _finding(system_id)
    with Session(db_engine) as session:
        record = PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()

    reconstructed = record.as_population_finding()

    assert reconstructed.population_finding_id == finding.population_finding_id
    assert reconstructed.classification_snapshot == finding.classification_snapshot
    assert not hasattr(reconstructed, "signature")
