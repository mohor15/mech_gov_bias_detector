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
