"""`verify_chain`'s thin Postgres-dependent shell — `verify_chain_from_database`
and the CLI wrapper — against a real database. CI-only (see
conftest.requires_postgres); the pure algorithm itself is fully covered
without a DB in tests/unit/audit/test_verify_chain.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.audit.signing import load_signer
from gov_platform.audit.verify_chain import main, verify_chain_from_database
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _verdict(decision_event_id: str, verdict_id: str) -> GovernanceVerdict:
    finding = Finding(
        finding_id=f"find-{verdict_id}",
        decision_event_id=decision_event_id,
        policy_id="always-allow",
        policy_version="0.1.0",
        outcome=FindingOutcome.CLEAR,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return GovernanceVerdict(
        verdict_id=verdict_id,
        decision_event_id=decision_event_id,
        status=VerdictStatus.ALLOW,
        findings=[finding],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_verify_chain_from_database_reports_the_real_chain_as_valid(
    evidence_store: EvidenceStore, make_decision_event: Any, postgres_url: str
) -> None:
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    result = verify_chain_from_database(postgres_url)

    assert result.valid is True
    assert result.checked_count >= 1


def test_cli_main_prints_the_result_and_exits_zero_when_valid(
    evidence_store: EvidenceStore, make_decision_event: Any, postgres_url: str, capsys: Any
) -> None:
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    exit_code = main(["--database-url", postgres_url])

    assert exit_code == 0
    assert "chain valid" in capsys.readouterr().out


def test_cli_main_fails_when_public_key_does_not_match_the_signing_key(
    db_engine: Engine, make_decision_event: Any, postgres_url: str, capsys: Any
) -> None:
    signer = load_signer(None)
    wrong_signer = load_signer(None)
    store = EvidenceStore(db_engine, signer=signer)
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    store.append(event, _verdict(event.event_id, str(uuid4())))

    exit_code = main(
        ["--database-url", postgres_url, "--public-key", wrong_signer.public_key_hex()]
    )

    assert exit_code == 1
    assert "signature" in capsys.readouterr().out
