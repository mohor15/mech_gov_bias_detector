"""The M1 acceptance criterion this milestone exists to prove: "an attempted
UPDATE/DELETE against the evidence tables is rejected at the DB privilege
level." CI-only — this is meaningless against anything but a real Postgres
connecting as the actual restricted role (see conftest.requires_postgres
and infra/migrations/0008_grant_evidence_chain_privileges.sql).

M6: `population_findings` gets the identical lockdown (migration `0015`)
— per `docs/milestones/M6.md` §13.16, a population finding is computed
governance output, evidentiary in the same sense a `Verdict` is, and a
"recompute" must always be a new row, never a silent rewrite of an
existing one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _seed_one_record(evidence_store: EvidenceStore, make_decision_event) -> int:
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    finding = Finding(
        finding_id=f"find-{uuid4()}",
        decision_event_id=event.event_id,
        policy_id="always-allow",
        policy_version="0.1.0",
        outcome=FindingOutcome.CLEAR,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=event.occurred_at,
    )
    verdict = GovernanceVerdict(
        verdict_id=f"verd-{uuid4()}",
        decision_event_id=event.event_id,
        status=VerdictStatus.ALLOW,
        findings=[finding],
        created_at=event.occurred_at,
    )
    record = evidence_store.append(event, verdict)
    return record.sequence_number


def test_update_on_evidence_chain_is_rejected_at_the_db_privilege_level(
    evidence_store: EvidenceStore, make_decision_event, db_engine
) -> None:
    sequence_number = _seed_one_record(evidence_store, make_decision_event)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("UPDATE evidence_chain SET payload = '{}' WHERE sequence_number = :seq"),
            {"seq": sequence_number},
        )
        session.commit()


def test_delete_on_evidence_chain_is_rejected_at_the_db_privilege_level(
    evidence_store: EvidenceStore, make_decision_event, db_engine
) -> None:
    sequence_number = _seed_one_record(evidence_store, make_decision_event)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("DELETE FROM evidence_chain WHERE sequence_number = :seq"),
            {"seq": sequence_number},
        )
        session.commit()


def test_insert_and_select_on_evidence_chain_are_still_permitted(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    # The negative control: this role isn't broken, it's specifically
    # missing UPDATE/DELETE. INSERT (via append) and SELECT (via get/all)
    # must keep working — already exercised by every other integration
    # test, asserted explicitly here as the direct counterpart to the two
    # rejection tests above.
    sequence_number = _seed_one_record(evidence_store, make_decision_event)
    assert evidence_store.get(sequence_number) is not None


def _seed_one_population_finding(db_engine) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"priv-test-system-{uuid4()}")
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system.id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.CLEAR,
            metric_values={},
            classification_snapshot={},
            rationale="test",
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        record = PopulationFindingRepository().create(
            session, finding, signature=None, signing_key_id=None
        )
        session.commit()
    return record.id


def test_update_on_population_findings_is_rejected_at_the_db_privilege_level(db_engine) -> None:
    finding_id = _seed_one_population_finding(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("UPDATE population_findings SET outcome = 'FLAGGED' WHERE id = :id"),
            {"id": finding_id},
        )
        session.commit()


def test_delete_on_population_findings_is_rejected_at_the_db_privilege_level(db_engine) -> None:
    finding_id = _seed_one_population_finding(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(text("DELETE FROM population_findings WHERE id = :id"), {"id": finding_id})
        session.commit()


def test_insert_and_select_on_population_findings_are_still_permitted(db_engine) -> None:
    finding_id = _seed_one_population_finding(db_engine)

    with Session(db_engine) as session:
        assert PopulationFindingRepository().get(session, finding_id) is not None
