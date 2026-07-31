"""`reporting/generate_report.py`'s thin Postgres-dependent shell — real
round trips through `main()`, `--database-url` and all. CI-only (see
conftest.requires_postgres); the dialect-independent pure logic (window
math, CSV flattening, CLI argument wiring) is covered without a DB in
`tests/unit/reporting/test_generate_report.py`, and
`get_compliance_report`'s own query correctness is covered in
`tests/integration/test_compliance_report_postgres.py`. This file exists
only to prove the CLI's real plumbing -- `create_db_engine`, a real
Postgres connection, real file output -- actually works end to end.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.reporting.generate_report import main
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _far_future_window() -> tuple[datetime, datetime]:
    start = datetime.now(UTC) + timedelta(days=3650)
    return start, start + timedelta(days=1)


def _seed_one_verdict(db_engine, *, evaluated_at: datetime, created_at: datetime) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"generate-report-cli-{uuid4()}")
        model_version = ModelVersionRepository().get_or_create(
            session, system_id=system.id, version=UNSPECIFIED_VERSION
        )
        event_id = f"evt-cli-report-{uuid4()}"
        event = DecisionEvent(
            event_id=event_id,
            system_id=system.name,
            decision_type="credit_decision",
            subject_ref=f"subj-{uuid4()}",
            occurred_at=evaluated_at,
            ingested_at=evaluated_at,
            input_features={},
            protected_attribute_refs={},
            decision_output={"approved": True},
        )
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)

        finding = Finding(
            finding_id=f"find-cli-report-{uuid4()}",
            decision_event_id=event_id,
            policy_id="cli-report-policy",
            policy_version="0.1.0",
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=evaluated_at,
        )
        FindingRepository().create(session, finding)

        verdict_id = f"verdict-cli-report-{uuid4()}"
        VerdictRepository().create(
            session,
            GovernanceVerdict(
                verdict_id=verdict_id,
                decision_event_id=event_id,
                status=VerdictStatus.ALLOW,
                findings=[finding],
                created_at=created_at,
            ),
        )
        session.commit()
    return verdict_id


def test_cli_writes_json_to_stdout_with_an_explicit_window(
    db_engine, postgres_url: str, capsys
) -> None:
    window_start = datetime.now(UTC)
    _seed_one_verdict(db_engine, evaluated_at=window_start, created_at=window_start)
    window_end = datetime.now(UTC) + timedelta(minutes=1)

    exit_code = main(
        [
            "--database-url",
            postgres_url,
            "--window-start",
            window_start.isoformat(),
            "--window-end",
            window_end.isoformat(),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["findings"]["by_policy"]["cli-report-policy"] == {"CLEAR": 1}
    assert report["verdicts"]["by_status"]["ALLOW"] >= 1


def test_cli_writes_json_to_a_file_when_output_is_given(
    db_engine, postgres_url: str, tmp_path: Path
) -> None:
    window_start, window_end = _far_future_window()
    output_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--database-url",
            postgres_url,
            "--window-start",
            window_start.isoformat(),
            "--window-end",
            window_end.isoformat(),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["verdicts"] == {"by_status": {}}
    assert report["reviews"] == {
        "verdict_reviews_by_resolution": {},
        "population_finding_reviews_by_resolution": {},
    }


def test_cli_writes_five_csv_files(db_engine, postgres_url: str, tmp_path: Path, capsys) -> None:
    window_start, window_end = _far_future_window()
    prefix = str(tmp_path / "monthly")

    exit_code = main(
        [
            "--database-url",
            postgres_url,
            "--window-start",
            window_start.isoformat(),
            "--window-end",
            window_end.isoformat(),
            "--format",
            "csv",
            "--output",
            prefix,
        ]
    )

    assert exit_code == 0
    for suffix in (
        "-verdicts.csv",
        "-findings.csv",
        "-population-findings.csv",
        "-verdict-reviews.csv",
        "-population-finding-reviews.csv",
    ):
        assert Path(f"{prefix}{suffix}").exists()
    out = capsys.readouterr().out
    assert out.count("WROTE") == 5


def test_cli_defaults_to_the_last_full_calendar_month_when_no_window_given(
    db_engine, postgres_url: str, capsys
) -> None:
    exit_code = main(["--database-url", postgres_url])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert "window_start" in report
    assert "window_end" in report
    assert report["system_id"] is None
