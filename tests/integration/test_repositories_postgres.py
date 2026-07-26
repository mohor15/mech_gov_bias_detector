"""Repository-level read paths (`get`, `list_by_*`) that EvidenceStore's
happy-path `append` never exercises — it only ever calls `create`/
`get_or_create`. These reads are the layer a future Admin API expansion
(see M1's "Explicit ModelVersion registration API" deferred item) will
build on, so they're tested directly against a real Postgres here rather
than left to whichever milestone first calls them. CI-only (see
conftest.requires_postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _finding(decision_event_id: str, **overrides: Any) -> Finding:
    defaults: dict[str, Any] = {
        "finding_id": f"find-{uuid4()}",
        "decision_event_id": decision_event_id,
        "policy_id": "always-allow",
        "policy_version": "0.1.0",
        "outcome": FindingOutcome.CLEAR,
        "confidence": 1.0,
        "rationale": "test",
        "metric_values": {"score": 0.1},
        "evaluated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Finding(**defaults)


def test_model_version_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert ModelVersionRepository().get(session, "does-not-exist") is None


def test_model_version_get_returns_the_created_row(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"sys-{uuid4()}")
        created = ModelVersionRepository().create(session, system_id=system.id, version="1.0.0")
        session.commit()

        fetched = ModelVersionRepository().get(session, created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.version == "1.0.0"


def test_model_version_list_by_system_returns_versions_in_creation_order(
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"sys-{uuid4()}")
        repo = ModelVersionRepository()
        first = repo.create(session, system_id=system.id, version="1.0.0")
        second = repo.create(session, system_id=system.id, version="2.0.0")
        session.commit()

        versions = repo.list_by_system(session, system.id)

    assert [v.id for v in versions] == [first.id, second.id]


def test_decision_event_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert DecisionEventRepository().get(session, "does-not-exist") is None


def test_decision_event_get_round_trips_and_resolves_system_name(
    db_engine: Engine, make_decision_event: Any
) -> None:
    with Session(db_engine) as session:
        system_name = f"sys-{uuid4()}"
        system = SystemRepository().create(session, name=system_name)
        model_version = ModelVersionRepository().create(
            session, system_id=system.id, version="1.0.0"
        )
        event = make_decision_event(event_id=f"evt-{uuid4()}", system_id=system_name)
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)
        session.commit()

        fetched = DecisionEventRepository().get(session, event.event_id)

    assert fetched is not None
    assert fetched.event_id == event.event_id
    assert fetched.system_id == system_name
    assert fetched.input_features == event.input_features


def test_finding_list_by_decision_event_orders_by_evaluated_at(
    db_engine: Engine, make_decision_event: Any
) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"sys-{uuid4()}")
        model_version = ModelVersionRepository().create(
            session, system_id=system.id, version="1.0.0"
        )
        event = make_decision_event(event_id=f"evt-{uuid4()}", system_id=system.name)
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)

        finding_repo = FindingRepository()
        later = _finding(event.event_id, evaluated_at=datetime(2026, 1, 2, tzinfo=UTC))
        earlier = _finding(event.event_id, evaluated_at=datetime(2026, 1, 1, tzinfo=UTC))
        finding_repo.create(session, later)
        finding_repo.create(session, earlier)
        session.commit()

        findings = finding_repo.list_by_decision_event(session, event.event_id)

    assert [f.finding_id for f in findings] == [earlier.finding_id, later.finding_id]


def test_verdict_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert VerdictRepository().get(session, "does-not-exist") is None


def test_verdict_get_round_trips_with_its_findings(
    db_engine: Engine, make_decision_event: Any
) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"sys-{uuid4()}")
        model_version = ModelVersionRepository().create(
            session, system_id=system.id, version="1.0.0"
        )
        event = make_decision_event(event_id=f"evt-{uuid4()}", system_id=system.name)
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)

        finding = _finding(event.event_id)
        FindingRepository().create(session, finding)

        verdict = GovernanceVerdict(
            verdict_id=f"verdict-{uuid4()}",
            decision_event_id=event.event_id,
            status=VerdictStatus.ALLOW,
            findings=[finding],
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        VerdictRepository().create(session, verdict)
        session.commit()

        fetched = VerdictRepository().get(session, verdict.verdict_id)

    assert fetched is not None
    assert fetched.verdict_id == verdict.verdict_id
    assert fetched.status == VerdictStatus.ALLOW
    assert [f.finding_id for f in fetched.findings] == [finding.finding_id]
