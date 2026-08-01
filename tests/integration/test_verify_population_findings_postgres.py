"""`verify_population_findings`'s thin Postgres-dependent shell —
`verify_population_findings_from_database` and the CLI wrapper — against a
real database. CI-only (see conftest.requires_postgres); the pure
algorithm itself is fully covered without a DB in
tests/unit/audit/test_verify_population_findings.py.

Deliberately does **not** assert "the whole table verifies as valid
against one specific key" the way it might for a fresh, isolated
database: `population_findings` is shared and append-only for the whole
test session (like `evidence_chain` — see
`test_evidence_store_postgres.py`'s docstring), and sibling test files
legitimately seed findings signed with other, unrelated keys (or
intentionally-invalid placeholder signature strings, to test the
repository layer's round-tripping in isolation, not real cryptographic
verification). Asserting whole-table success here would be exactly the
kind of test-order-dependent flakiness `test_verify_chain_postgres.py`'s
own suite already avoids (its "valid" test never passes `--public-key`
at all, for the identical reason). What's real Postgres-integration
behavior worth proving at this layer — that the DB-reading shell wires
through to the pure function correctly, and that a genuine key mismatch
is detected — is covered below without assuming table-wide isolation.
Whole-table-scoped, real success *is* covered, correctly isolated to one
system's own findings, in
`test_population_run_policies_postgres.py::test_the_signed_finding_verifies_against_the_configured_public_key`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from gov_platform.audit.signing import load_signer
from gov_platform.audit.verify_population_findings import (
    main,
    population_finding_hash,
    verify_population_findings_from_database,
)
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _seed_signed_finding(db_engine, signer) -> PopulationFinding:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"verify-test-system-{uuid4()}")
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system.id,
            # A deliberately, unambiguously earliest window/evaluated_at --
            # not `datetime.now(UTC)`, not any 2026 date another test in
            # this shared, never-truncated table might use. `list_all`
            # (this module's own `verify_population_findings_from_database`
            # target) orders by `evaluated_at` first, `id` only as a
            # tiebreaker (docs/milestones/M15.md §5.2); `checked_count == 0`
            # results whenever *any* row with a signature that doesn't
            # verify under this test's own fresh key sorts before this
            # one. Matching sibling files' own timestamps (whether a fixed
            # 2026 date or `datetime.now(UTC)`) only ever proves "not tied
            # with what exists today" -- it does not prove "sorts first,"
            # since nothing guarantees another row's timestamp, now or in
            # the future, stays later than whatever this file picks. An
            # intentionally out-of-band, far-earlier sentinel is the only
            # version of this fix that does not depend on what any other
            # test (or the real wall clock a CI runner happens to have)
            # does. See `docs/milestones/M15.md` — two prior attempts at
            # this fix each matched some, but not all, sibling timestamps
            # and CI failed on this exact assertion both times.
            window_start=datetime(2000, 1, 1, tzinfo=UTC),
            window_end=datetime(2000, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.CLEAR,
            metric_values={},
            classification_snapshot={"race": "DIRECT"},
            rationale="test",
            evaluated_at=datetime(2000, 1, 2, tzinfo=UTC),
        )
        signature = signer.sign(population_finding_hash(finding))
        PopulationFindingRepository().create(
            session, finding, signature=signature, signing_key_id=signer.key_id
        )
        session.commit()
    return finding


def test_verify_from_database_reads_real_rows_and_reports_a_checked_count(
    db_engine, postgres_url
) -> None:
    signer = load_signer(None)
    _seed_signed_finding(db_engine, signer)

    # Not asserting `valid is True` -- the shared, append-only table may
    # already carry findings signed with other keys, seeded by sibling
    # test files (see this module's docstring). What's genuinely provable
    # at this layer is that the DB-reading shell actually reads real rows.
    result = verify_population_findings_from_database(
        postgres_url, public_key_hex=signer.public_key_hex()
    )

    assert result.checked_count >= 1


def test_cli_main_prints_a_result_line(db_engine, postgres_url, capsys) -> None:
    signer = load_signer(None)
    _seed_signed_finding(db_engine, signer)

    exit_code = main(["--database-url", postgres_url, "--public-key", signer.public_key_hex()])

    assert exit_code in (0, 1)
    assert "checked" in capsys.readouterr().out


def test_cli_main_fails_when_public_key_does_not_match_the_signing_key(
    db_engine, postgres_url, capsys
) -> None:
    signer = load_signer(None)
    wrong_signer = load_signer(None)
    _seed_signed_finding(db_engine, signer)

    exit_code = main(
        ["--database-url", postgres_url, "--public-key", wrong_signer.public_key_hex()]
    )

    assert exit_code == 1
    assert "signature" in capsys.readouterr().out
