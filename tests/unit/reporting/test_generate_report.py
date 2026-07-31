"""`reporting.generate_report`'s dialect-independent pure logic and CLI
wiring — no DB. `get_compliance_report` itself is exercised only against a
real Postgres instance, in
`tests/integration/test_generate_report_postgres.py`.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from gov_platform.reporting import generate_report
from gov_platform.reporting.compliance_report import (
    ComplianceReport,
    FindingCounts,
    PopulationFindingCounts,
    ReviewOutcomeCounts,
    VerdictCounts,
)
from gov_platform.reporting.generate_report import (
    _flat_rows,
    _nested_flat_rows,
    default_window,
    main,
    write_csv_files,
)


def _make_report(**overrides: object) -> ComplianceReport:
    defaults: dict[str, object] = {
        "window_start": datetime(2026, 6, 1, tzinfo=UTC),
        "window_end": datetime(2026, 7, 1, tzinfo=UTC),
        "system_id": None,
        "verdicts": VerdictCounts(by_status={"ALLOW": 3, "ESCALATE_FOR_REVIEW": 1}),
        "findings": FindingCounts(
            by_policy={"direct-attribute-in-inputs": {"CLEAR": 2, "FLAGGED": 1}}
        ),
        "population_findings": PopulationFindingCounts(
            by_policy={"adverse-impact-ratio": {"CLEAR": 1}}
        ),
        "reviews": ReviewOutcomeCounts(
            verdict_reviews_by_resolution={"CONFIRMED": 1, "DISMISSED": 2},
            population_finding_reviews_by_resolution={"CONFIRMED": 1},
        ),
        "generated_at": datetime(2026, 7, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ComplianceReport(**defaults)  # type: ignore[arg-type]


# --- default_window ---------------------------------------------------


def test_default_window_returns_the_last_full_calendar_month() -> None:
    as_of = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

    window_start, window_end = default_window(as_of)

    assert window_start == datetime(2026, 6, 1, tzinfo=UTC)
    assert window_end == datetime(2026, 7, 1, tzinfo=UTC)


def test_default_window_wraps_around_january_to_december_of_the_prior_year() -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)

    window_start, window_end = default_window(as_of)

    assert window_start == datetime(2025, 12, 1, tzinfo=UTC)
    assert window_end == datetime(2026, 1, 1, tzinfo=UTC)


def test_default_window_ignores_the_day_and_time_of_day_component() -> None:
    early = default_window(datetime(2026, 7, 1, 0, 0, 1, tzinfo=UTC))
    late = default_window(datetime(2026, 7, 30, 23, 59, 59, tzinfo=UTC))

    assert early == late


def test_default_window_defaults_to_now_when_as_of_is_omitted() -> None:
    window_start, window_end = default_window()

    assert window_start < window_end
    assert window_end.tzinfo is UTC
    assert window_start.day == 1
    assert window_end.day == 1


# --- CSV row flattening --------------------------------------------------


def test_flat_rows_sorts_by_key() -> None:
    assert _flat_rows({"DISMISSED": 2, "CONFIRMED": 1}) == [("CONFIRMED", 1), ("DISMISSED", 2)]


def test_flat_rows_empty_dict_is_empty_list() -> None:
    assert _flat_rows({}) == []


def test_nested_flat_rows_sorts_by_outer_then_inner_key() -> None:
    rows = _nested_flat_rows({"policy-b": {"FLAGGED": 1, "CLEAR": 2}, "policy-a": {"CLEAR": 3}})

    assert rows == [
        ("policy-a", "CLEAR", 3),
        ("policy-b", "CLEAR", 2),
        ("policy-b", "FLAGGED", 1),
    ]


def test_nested_flat_rows_empty_dict_is_empty_list() -> None:
    assert _nested_flat_rows({}) == []


# --- write_csv_files -------------------------------------------------------


def test_write_csv_files_writes_five_files_with_the_expected_names(tmp_path: Path) -> None:
    report = _make_report()
    prefix = str(tmp_path / "report")

    paths = write_csv_files(report, prefix)

    assert [p.name for p in paths] == [
        "report-verdicts.csv",
        "report-findings.csv",
        "report-population-findings.csv",
        "report-verdict-reviews.csv",
        "report-population-finding-reviews.csv",
    ]
    for path in paths:
        assert path.exists()


def test_write_csv_files_verdicts_content(tmp_path: Path) -> None:
    report = _make_report()
    prefix = str(tmp_path / "report")

    write_csv_files(report, prefix)

    with open(f"{prefix}-verdicts.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == ["status", "count"]
    assert ["ALLOW", "3"] in rows[1:]
    assert ["ESCALATE_FOR_REVIEW", "1"] in rows[1:]


def test_write_csv_files_findings_content_is_flattened_policy_outcome_count(
    tmp_path: Path,
) -> None:
    report = _make_report()
    prefix = str(tmp_path / "report")

    write_csv_files(report, prefix)

    with open(f"{prefix}-findings.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == ["policy_id", "outcome", "count"]
    assert ["direct-attribute-in-inputs", "CLEAR", "2"] in rows[1:]
    assert ["direct-attribute-in-inputs", "FLAGGED", "1"] in rows[1:]


def test_write_csv_files_review_outcomes_split_into_two_separate_files(tmp_path: Path) -> None:
    report = _make_report()
    prefix = str(tmp_path / "report")

    write_csv_files(report, prefix)

    with open(f"{prefix}-verdict-reviews.csv", newline="", encoding="utf-8") as handle:
        verdict_review_rows = list(csv.reader(handle))
    with open(f"{prefix}-population-finding-reviews.csv", newline="", encoding="utf-8") as handle:
        population_finding_review_rows = list(csv.reader(handle))

    assert verdict_review_rows[0] == ["resolution", "count"]
    assert ["CONFIRMED", "1"] in verdict_review_rows[1:]
    assert ["DISMISSED", "2"] in verdict_review_rows[1:]

    assert population_finding_review_rows[0] == ["resolution", "count"]
    assert population_finding_review_rows[1:] == [["CONFIRMED", "1"]]


def test_write_csv_files_empty_sections_still_write_a_header_only_file(tmp_path: Path) -> None:
    report = _make_report(
        population_findings=PopulationFindingCounts(by_policy={}),
    )
    prefix = str(tmp_path / "report")

    write_csv_files(report, prefix)

    with open(f"{prefix}-population-findings.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [["population_policy_id", "outcome", "count"]]


# --- CLI wiring: main() delegates to create_db_engine/get_compliance_report,
# mocked here to avoid needing a real database connection --------------------


def test_main_requires_database_url() -> None:
    with pytest.raises(SystemExit):
        main(["--format", "json"])


def test_main_rejects_window_start_without_window_end() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--database-url",
                "postgresql+psycopg://user@localhost/gov_platform",
                "--window-start",
                "2026-06-01T00:00:00+00:00",
            ]
        )


def test_main_rejects_window_end_without_window_start() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--database-url",
                "postgresql+psycopg://user@localhost/gov_platform",
                "--window-end",
                "2026-07-01T00:00:00+00:00",
            ]
        )


def test_main_rejects_csv_format_with_no_output() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--database-url",
                "postgresql+psycopg://user@localhost/gov_platform",
                "--format",
                "csv",
            ]
        )


def _patch_engine_and_report(
    monkeypatch: pytest.MonkeyPatch, report: ComplianceReport
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_db_engine(database_url: str) -> str:
        captured["database_url"] = database_url
        return "fake-engine"

    def fake_get_compliance_report(
        engine: Any,
        *,
        window_start: datetime,
        window_end: datetime,
        system_id: str | None = None,
    ) -> ComplianceReport:
        captured["engine"] = engine
        captured["window_start"] = window_start
        captured["window_end"] = window_end
        captured["system_id"] = system_id
        return report

    monkeypatch.setattr(generate_report, "create_db_engine", fake_create_db_engine)
    monkeypatch.setattr(generate_report, "get_compliance_report", fake_get_compliance_report)
    return captured


def test_main_writes_json_to_stdout_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _make_report()
    _patch_engine_and_report(monkeypatch, report)

    exit_code = main(["--database-url", "postgresql+psycopg://user@localhost/gov_platform"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert '"ALLOW": 3' in out
    assert '"window_start": "2026-06-01T00:00:00Z"' in out


def test_main_writes_json_to_a_file_when_output_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = _make_report()
    _patch_engine_and_report(monkeypatch, report)
    output_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--database-url",
            "postgresql+psycopg://user@localhost/gov_platform",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    assert '"ALLOW": 3' in output_path.read_text(encoding="utf-8")


def test_main_writes_five_csv_files_when_format_is_csv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _make_report()
    _patch_engine_and_report(monkeypatch, report)
    prefix = str(tmp_path / "monthly")

    exit_code = main(
        [
            "--database-url",
            "postgresql+psycopg://user@localhost/gov_platform",
            "--format",
            "csv",
            "--output",
            prefix,
        ]
    )

    assert exit_code == 0
    assert Path(f"{prefix}-verdicts.csv").exists()
    assert Path(f"{prefix}-verdict-reviews.csv").exists()
    assert Path(f"{prefix}-population-finding-reviews.csv").exists()
    out = capsys.readouterr().out
    assert "WROTE" in out


def test_main_passes_explicit_window_and_system_id_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _make_report()
    captured = _patch_engine_and_report(monkeypatch, report)

    exit_code = main(
        [
            "--database-url",
            "postgresql+psycopg://user@localhost/gov_platform",
            "--window-start",
            "2026-05-01T00:00:00+00:00",
            "--window-end",
            "2026-06-01T00:00:00+00:00",
            "--system-id",
            "credit-scorecard-prod",
        ]
    )

    assert exit_code == 0
    assert captured["window_start"] == datetime(2026, 5, 1, tzinfo=UTC)
    assert captured["window_end"] == datetime(2026, 6, 1, tzinfo=UTC)
    assert captured["system_id"] == "credit-scorecard-prod"
    assert captured["database_url"] == "postgresql+psycopg://user@localhost/gov_platform"


def test_main_defaults_to_last_full_calendar_month_when_no_window_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _make_report()
    captured = _patch_engine_and_report(monkeypatch, report)
    monkeypatch.setattr(
        generate_report,
        "default_window",
        lambda: (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
    )

    exit_code = main(["--database-url", "postgresql+psycopg://user@localhost/gov_platform"])

    assert exit_code == 0
    assert captured["window_start"] == datetime(2026, 6, 1, tzinfo=UTC)
    assert captured["window_end"] == datetime(2026, 7, 1, tzinfo=UTC)
    assert captured["system_id"] is None
