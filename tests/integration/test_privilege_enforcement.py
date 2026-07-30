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

M11 (architecture §13): migration `0025` extends the identical lockdown to
`systems`, `model_versions`, `decision_events`, `findings`, `verdicts`, and
`verdict_findings` — closing `docs/milestones/M9.md` §9.5's disclosed gap.
Migration `0026` additionally revokes `DELETE`/`UPDATE` from
`gov_platform_app` on `shadow_findings`/`protected_attribute_resolutions`
(retention-eligible, but not evidentiary — only the retention tool's own
separately-credentialed connection may delete from either; see
`test_purge_expired_records_postgres.py`). Both migrations are verified
here to change *only* `gov_platform_app`'s own privileges — the same
elevated `admin_database_url` connection the retention tool and
`db/migrate.py` use can still delete freely, proven directly rather than
assumed (docs/milestones/M11.md §12.8's own "the lockdown is a statement
about what these tables are, not a technical capability boundary").
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
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)
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


def _seed_one_full_record(
    evidence_store: EvidenceStore, make_decision_event, db_engine
) -> dict[str, str]:
    """Seeds one governed decision touching all six of migration `0025`'s
    tables (systems, model_versions, decision_events, findings, verdicts,
    verdict_findings) plus `shadow_findings`/`protected_attribute_resolutions`
    (migration `0026`), returning every id `0025`/`0026`'s own tests need."""
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    finding_id = f"find-{verdict_id}"
    finding = Finding(
        finding_id=finding_id,
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
        verdict_id=verdict_id,
        decision_event_id=event.event_id,
        status=VerdictStatus.ALLOW,
        findings=[finding],
        created_at=event.occurred_at,
    )
    evidence_store.append(event, verdict)

    with Session(db_engine) as session:
        system_id = session.execute(
            text("SELECT id FROM systems WHERE name = :name"), {"name": event.system_id}
        ).scalar_one()
        model_version_id = session.execute(
            text("SELECT id FROM model_versions WHERE system_id = :system_id"),
            {"system_id": system_id},
        ).scalar_one()

    return {
        "system_id": system_id,
        "model_version_id": model_version_id,
        "decision_event_id": event.event_id,
        "finding_id": finding_id,
        "verdict_id": verdict_id,
    }


@pytest.mark.parametrize(
    ("table", "id_column", "id_key"),
    [
        ("systems", "id", "system_id"),
        ("model_versions", "id", "model_version_id"),
        ("decision_events", "id", "decision_event_id"),
        ("findings", "id", "finding_id"),
        ("verdicts", "id", "verdict_id"),
    ],
)
def test_update_is_rejected_on_each_m11_locked_operational_table(
    evidence_store, make_decision_event, db_engine, table, id_column, id_key
) -> None:
    """M11 §5.3/§9.5: closes docs/milestones/M9.md's disclosed gap -- these
    five tables (plus verdict_findings, tested separately below since it
    has a composite key) never had evidence_chain's/population_findings'
    own append-only lockdown before migration 0025."""
    ids = _seed_one_full_record(evidence_store, make_decision_event, db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text(f"UPDATE {table} SET {id_column} = {id_column} WHERE {id_column} = :id"),
            {"id": ids[id_key]},
        )
        session.commit()


@pytest.mark.parametrize(
    ("table", "id_column", "id_key"),
    [
        ("systems", "id", "system_id"),
        ("model_versions", "id", "model_version_id"),
        ("decision_events", "id", "decision_event_id"),
        ("findings", "id", "finding_id"),
        ("verdicts", "id", "verdict_id"),
    ],
)
def test_delete_is_rejected_on_each_m11_locked_operational_table(
    evidence_store, make_decision_event, db_engine, table, id_column, id_key
) -> None:
    ids = _seed_one_full_record(evidence_store, make_decision_event, db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(text(f"DELETE FROM {table} WHERE {id_column} = :id"), {"id": ids[id_key]})
        session.commit()


def test_update_on_verdict_findings_is_rejected_at_the_db_privilege_level(
    evidence_store, make_decision_event, db_engine
) -> None:
    ids = _seed_one_full_record(evidence_store, make_decision_event, db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("UPDATE verdict_findings SET verdict_id = verdict_id WHERE verdict_id = :id"),
            {"id": ids["verdict_id"]},
        )
        session.commit()


def test_delete_on_verdict_findings_is_rejected_at_the_db_privilege_level(
    evidence_store, make_decision_event, db_engine
) -> None:
    ids = _seed_one_full_record(evidence_store, make_decision_event, db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("DELETE FROM verdict_findings WHERE verdict_id = :id"), {"id": ids["verdict_id"]}
        )
        session.commit()


def test_insert_and_select_still_work_across_all_six_m11_locked_tables(
    evidence_store, make_decision_event, db_engine
) -> None:
    # The negative control: gov_platform_app isn't broken, it's specifically
    # missing UPDATE/DELETE. A full append (which INSERTs into all six) and
    # a subsequent read must keep working.
    ids = _seed_one_full_record(evidence_store, make_decision_event, db_engine)
    assert all(ids.values())


def _seed_one_shadow_finding(db_engine) -> dict[str, str]:
    from gov_platform.db.repositories.decision_event import DecisionEventRepository
    from gov_platform.db.repositories.model_version import ModelVersionRepository
    from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
    from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
    from gov_platform.schemas.decision_event import DecisionEvent
    from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
    from gov_platform.schemas.plugin_registration import PluginType

    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"priv-shadow-system-{uuid4()}")
        model_version = ModelVersionRepository().get_or_create(
            session, system_id=system.id, version=UNSPECIFIED_VERSION
        )
        event = DecisionEvent(
            event_id=f"evt-shadow-{uuid4()}",
            system_id=system.name,
            decision_type="credit_decision",
            subject_ref=f"subj-{uuid4()}",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
            input_features={},
            protected_attribute_refs={},
            decision_output={"approved": True},
        )
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)
        registration = PluginRegistrationRepository().create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id="always-allow",
            version=f"priv-test-{uuid4()}",
        )
        PluginRegistrationRepository().promote(session, registration.id)  # DRAFT -> SHADOW
        finding = Finding(
            finding_id=f"shadow-find-{uuid4()}",
            decision_event_id=event.event_id,
            policy_id="always-allow",
            policy_version="0.1.0",
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        ShadowFindingRepository().create(session, finding, plugin_registration_id=registration.id)
        session.commit()

        shadow_finding_id = session.execute(
            text("SELECT id FROM shadow_findings WHERE decision_event_id = :id"),
            {"id": event.event_id},
        ).scalar_one()

    return {"shadow_finding_id": shadow_finding_id}


def test_update_on_shadow_findings_is_rejected_at_the_db_privilege_level(db_engine) -> None:
    ids = _seed_one_shadow_finding(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("UPDATE shadow_findings SET outcome = 'FLAGGED' WHERE id = :id"),
            {"id": ids["shadow_finding_id"]},
        )
        session.commit()


def test_delete_on_shadow_findings_is_rejected_at_the_db_privilege_level(db_engine) -> None:
    ids = _seed_one_shadow_finding(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("DELETE FROM shadow_findings WHERE id = :id"), {"id": ids["shadow_finding_id"]}
        )
        session.commit()


def _seed_one_protected_attribute_resolution(db_engine) -> dict[str, str]:
    from gov_platform.db.repositories.decision_event import DecisionEventRepository
    from gov_platform.db.repositories.model_version import ModelVersionRepository
    from gov_platform.db.repositories.protected_attribute_resolution import (
        ProtectedAttributeResolutionRepository,
    )
    from gov_platform.schemas.decision_event import DecisionEvent
    from gov_platform.schemas.model_version import UNSPECIFIED_VERSION

    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"priv-par-system-{uuid4()}")
        model_version = ModelVersionRepository().get_or_create(
            session, system_id=system.id, version=UNSPECIFIED_VERSION
        )
        event = DecisionEvent(
            event_id=f"evt-par-{uuid4()}",
            system_id=system.name,
            decision_type="credit_decision",
            subject_ref=f"subj-{uuid4()}",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
            input_features={},
            protected_attribute_refs={},
            decision_output={"approved": True},
        )
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)
        ProtectedAttributeResolutionRepository().create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="race",
                classification=ProtectedAttributeClassification.DIRECT,
                resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        session.commit()

        resolution_id = session.execute(
            text("SELECT id FROM protected_attribute_resolutions WHERE decision_event_id = :id"),
            {"id": event.event_id},
        ).scalar_one()

    return {"resolution_id": resolution_id}


def test_update_on_protected_attribute_resolutions_is_rejected_at_the_db_privilege_level(
    db_engine,
) -> None:
    ids = _seed_one_protected_attribute_resolution(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text(
                "UPDATE protected_attribute_resolutions SET classification = 'PROXIED' "
                "WHERE id = :id"
            ),
            {"id": ids["resolution_id"]},
        )
        session.commit()


def test_delete_on_protected_attribute_resolutions_is_rejected_at_the_db_privilege_level(
    db_engine,
) -> None:
    ids = _seed_one_protected_attribute_resolution(db_engine)

    with Session(db_engine) as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(
            text("DELETE FROM protected_attribute_resolutions WHERE id = :id"),
            {"id": ids["resolution_id"]},
        )
        session.commit()


def test_admin_connection_can_still_delete_from_a_retention_eligible_table(
    admin_db_engine, db_engine
) -> None:
    """docs/milestones/M11.md §12.8: the lockdown is a statement about what
    these tables *are* to the running application, not a technical
    capability boundary -- the elevated connection the retention tool and
    db/migrate.py use is unaffected, proven directly against
    shadow_findings rather than merely assumed from migration 0026's own
    SQL text."""
    ids = _seed_one_shadow_finding(db_engine)

    with Session(admin_db_engine) as session:
        session.execute(
            text("DELETE FROM shadow_findings WHERE id = :id"), {"id": ids["shadow_finding_id"]}
        )
        session.commit()

    with Session(db_engine) as session:
        remaining = session.execute(
            text("SELECT COUNT(*) FROM shadow_findings WHERE id = :id"),
            {"id": ids["shadow_finding_id"]},
        ).scalar_one()
    assert remaining == 0


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
