"""`purge_expired_records`'s dialect-independent pure logic and CLI
wiring — no DB. `purge_shadow_findings`/`purge_protected_attribute_resolutions`/
`run_purge` themselves execute real ORM-backed `DELETE` statements against
`shadow_findings`/`protected_attribute_resolutions` and are exercised only
against a real Postgres instance, in
`tests/integration/test_purge_expired_records_postgres.py` — this project's
models are never used to generate DDL against any other dialect (see
`db/models.py`'s own module docstring), so there is no SQLite stand-in for
them here, unlike `db/migrate.py`'s dialect-agnostic runner mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from gov_platform.retention.purge_expired_records import PurgeResult, compute_cutoff, main


def test_compute_cutoff_subtracts_retention_days_from_now() -> None:
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

    cutoff = compute_cutoff(30, now=now)

    assert cutoff == datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def test_compute_cutoff_zero_days_means_the_cutoff_is_now() -> None:
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

    assert compute_cutoff(0, now=now) == now


def test_purge_result_skipped_carries_no_cutoff_or_deletions() -> None:
    result = PurgeResult(
        table_name="shadow_findings",
        retention_days=None,
        cutoff=None,
        deleted_count=0,
        skipped=True,
    )

    assert result.skipped is True
    assert result.cutoff is None
    assert result.deleted_count == 0


# --- CLI wiring: main() delegates to run_purge/get_settings, mocked here to
# avoid needing a real database connection (SQLAlchemy engines are lazy, but
# run_purge itself opens a real Session and executes a DELETE) ------------


def test_main_requires_database_url(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])


def test_main_reads_retention_settings_and_reports_purge_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gov_platform.config.settings import Settings
    from gov_platform.retention import purge_expired_records

    captured: dict[str, Any] = {}

    def fake_create_db_engine(database_url: str) -> str:
        captured["database_url"] = database_url
        return "fake-engine"

    def fake_run_purge(
        engine: Any,
        *,
        retention_days_shadow_findings: int | None,
        retention_days_protected_attribute_resolutions: int | None,
        now: datetime | None = None,
    ) -> list[PurgeResult]:
        captured["engine"] = engine
        captured["retention_days_shadow_findings"] = retention_days_shadow_findings
        captured["retention_days_protected_attribute_resolutions"] = (
            retention_days_protected_attribute_resolutions
        )
        return [
            PurgeResult(
                table_name="shadow_findings",
                retention_days=retention_days_shadow_findings,
                cutoff=datetime(2026, 6, 1, tzinfo=UTC),
                deleted_count=3,
                skipped=False,
            ),
            PurgeResult(
                table_name="protected_attribute_resolutions",
                retention_days=None,
                cutoff=None,
                deleted_count=0,
                skipped=True,
            ),
        ]

    monkeypatch.setattr(purge_expired_records, "create_db_engine", fake_create_db_engine)
    monkeypatch.setattr(purge_expired_records, "run_purge", fake_run_purge)
    monkeypatch.setattr(
        purge_expired_records,
        "get_settings",
        lambda: Settings(RETENTION_DAYS_SHADOW_FINDINGS=90),
    )

    exit_code = main(["--database-url", "postgresql+psycopg://elevated@localhost/gov_platform"])

    assert exit_code == 0
    assert captured["database_url"] == "postgresql+psycopg://elevated@localhost/gov_platform"
    assert captured["retention_days_shadow_findings"] == 90
    assert captured["retention_days_protected_attribute_resolutions"] is None

    out = capsys.readouterr().out
    assert "PURGED shadow_findings: 3 row(s)" in out
    assert "SKIP protected_attribute_resolutions: no retention window configured" in out
