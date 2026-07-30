"""`retention/purge_expired_records.py`'s thin Postgres-dependent shell —
real `DELETE` round trips against `shadow_findings` and
`protected_attribute_resolutions`. CI-only (see conftest.requires_postgres);
the dialect-independent pure logic (`compute_cutoff`, CLI wiring) is
covered without a DB in
`tests/unit/retention/test_purge_expired_records.py`.

Runs under `admin_db_engine` (the elevated, migration-owner connection —
docs/milestones/M11.md §5.2/§12.11): as of migration `0026`,
`gov_platform_app` (the connection every other integration test's
`db_engine` authenticates as) has no `DELETE` privilege on either table at
all — proven directly in `test_privilege_enforcement.py`, relied on here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.protected_attribute_resolution import (
    ProtectedAttributeResolutionRepository,
)
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.retention.purge_expired_records import main, run_purge
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
from gov_platform.schemas.plugin_registration import PluginType
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)
from tests.conftest import requires_admin_postgres, requires_postgres

pytestmark = [requires_postgres, requires_admin_postgres]


def _seed_decision_event(db_engine) -> DecisionEvent:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"retention-test-{uuid4()}")
        model_version = ModelVersionRepository().get_or_create(
            session, system_id=system.id, version=UNSPECIFIED_VERSION
        )
        event = DecisionEvent(
            event_id=f"evt-retention-{uuid4()}",
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
        session.commit()
    return event


def _seed_shadow_finding(db_engine, *, evaluated_at: datetime) -> str:
    event = _seed_decision_event(db_engine)
    with Session(db_engine) as session:
        registration = PluginRegistrationRepository().create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id="always-allow",
            version=f"retention-test-{uuid4()}",
        )
        finding = Finding(
            finding_id=f"shadow-find-{uuid4()}",
            decision_event_id=event.event_id,
            policy_id="always-allow",
            policy_version="0.1.0",
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=evaluated_at,
        )
        ShadowFindingRepository().create(session, finding, plugin_registration_id=registration.id)
        session.commit()

        shadow_finding_id: str = session.execute(
            text("SELECT id FROM shadow_findings WHERE decision_event_id = :id"),
            {"id": event.event_id},
        ).scalar_one()
    return shadow_finding_id


def _seed_protected_attribute_resolution(db_engine, *, resolved_at: datetime) -> str:
    event = _seed_decision_event(db_engine)
    with Session(db_engine) as session:
        ProtectedAttributeResolutionRepository().create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="race",
                classification=ProtectedAttributeClassification.DIRECT,
                resolved_at=resolved_at,
            ),
        )
        session.commit()

        resolution_id: str = session.execute(
            text("SELECT id FROM protected_attribute_resolutions WHERE decision_event_id = :id"),
            {"id": event.event_id},
        ).scalar_one()
    return resolution_id


def _shadow_finding_exists(db_engine, shadow_finding_id: str) -> bool:
    with Session(db_engine) as session:
        count = session.execute(
            text("SELECT COUNT(*) FROM shadow_findings WHERE id = :id"), {"id": shadow_finding_id}
        ).scalar_one()
    return bool(count)


def _resolution_exists(db_engine, resolution_id: str) -> bool:
    with Session(db_engine) as session:
        count = session.execute(
            text("SELECT COUNT(*) FROM protected_attribute_resolutions WHERE id = :id"),
            {"id": resolution_id},
        ).scalar_one()
    return bool(count)


def test_purge_deletes_shadow_findings_older_than_the_cutoff(db_engine, admin_db_engine) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    old_id = _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=100))

    results = run_purge(
        admin_db_engine,
        retention_days_shadow_findings=90,
        retention_days_protected_attribute_resolutions=None,
        now=now,
    )

    assert not _shadow_finding_exists(db_engine, old_id)
    shadow_result = next(r for r in results if r.table_name == "shadow_findings")
    assert shadow_result.deleted_count >= 1
    assert shadow_result.skipped is False


def test_purge_keeps_shadow_findings_newer_than_the_cutoff(db_engine, admin_db_engine) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    recent_id = _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=1))

    run_purge(
        admin_db_engine,
        retention_days_shadow_findings=90,
        retention_days_protected_attribute_resolutions=None,
        now=now,
    )

    assert _shadow_finding_exists(db_engine, recent_id)


def test_purge_deletes_protected_attribute_resolutions_older_than_the_cutoff(
    db_engine, admin_db_engine
) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    old_id = _seed_protected_attribute_resolution(db_engine, resolved_at=now - timedelta(days=400))

    results = run_purge(
        admin_db_engine,
        retention_days_shadow_findings=None,
        retention_days_protected_attribute_resolutions=365,
        now=now,
    )

    assert not _resolution_exists(db_engine, old_id)
    par_result = next(r for r in results if r.table_name == "protected_attribute_resolutions")
    assert par_result.deleted_count >= 1


def test_purge_keeps_protected_attribute_resolutions_newer_than_the_cutoff(
    db_engine, admin_db_engine
) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    recent_id = _seed_protected_attribute_resolution(db_engine, resolved_at=now - timedelta(days=1))

    run_purge(
        admin_db_engine,
        retention_days_shadow_findings=None,
        retention_days_protected_attribute_resolutions=365,
        now=now,
    )

    assert _resolution_exists(db_engine, recent_id)


def test_purge_skips_a_table_with_no_configured_retention_window(
    db_engine, admin_db_engine
) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    old_id = _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=10000))

    results = run_purge(
        admin_db_engine,
        retention_days_shadow_findings=None,
        retention_days_protected_attribute_resolutions=None,
        now=now,
    )

    assert _shadow_finding_exists(db_engine, old_id)  # untouched -- no window configured
    assert all(r.skipped for r in results)
    assert all(r.deleted_count == 0 for r in results)


def test_purge_is_idempotent_a_second_run_deletes_nothing_more(db_engine, admin_db_engine) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=100))

    first_run = run_purge(
        admin_db_engine,
        retention_days_shadow_findings=90,
        retention_days_protected_attribute_resolutions=None,
        now=now,
    )
    second_run = run_purge(
        admin_db_engine,
        retention_days_shadow_findings=90,
        retention_days_protected_attribute_resolutions=None,
        now=now,
    )

    shadow_first = next(r for r in first_run if r.table_name == "shadow_findings")
    shadow_second = next(r for r in second_run if r.table_name == "shadow_findings")
    assert shadow_first.deleted_count >= 1
    assert shadow_second.deleted_count == 0  # already purged -- clean no-op


def test_the_ordinary_app_role_cannot_run_the_purge_itself(db_engine) -> None:
    """The retention tool's own elevated connection is load-bearing, not
    incidental: gov_platform_app has no DELETE on either retention-eligible
    table as of migration 0026 (see test_privilege_enforcement.py), so
    run_purge against the ordinary db_engine must fail loudly, never
    silently no-op."""
    import pytest
    from sqlalchemy.exc import DBAPIError

    now = datetime(2026, 7, 30, tzinfo=UTC)
    _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=100))

    with pytest.raises(DBAPIError, match="permission denied"):
        run_purge(
            db_engine,
            retention_days_shadow_findings=90,
            retention_days_protected_attribute_resolutions=None,
            now=now,
        )


def test_cli_main_end_to_end(db_engine, admin_database_url, monkeypatch, capsys) -> None:
    from gov_platform.config.settings import Settings
    from gov_platform.retention import purge_expired_records

    now = datetime(2026, 7, 30, tzinfo=UTC)
    _seed_shadow_finding(db_engine, evaluated_at=now - timedelta(days=100))

    monkeypatch.setattr(
        purge_expired_records,
        "get_settings",
        lambda: Settings(RETENTION_DAYS_SHADOW_FINDINGS=90),
    )

    exit_code = main(["--database-url", admin_database_url])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PURGED shadow_findings" in out
    assert "SKIP protected_attribute_resolutions" in out
