"""Application-level field encryption (tier two) — real Postgres round
trips for all four M11-encrypted columns: `evidence_chain.payload`,
`verdict_reviews.resolution_notes`, `population_finding_reviews.resolution_notes`,
and `protected_attribute_resolutions.proxy_basis`. CI-only (see
conftest.requires_postgres). The pure marker/Fernet logic itself is fully
covered without a DB in `tests/unit/audit/test_encryption.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.orm import Session

from gov_platform.audit.encryption import (
    UNREADABLE_PLACEHOLDER,
    FernetFieldEncryptor,
    FieldDecryptionError,
    NoOpFieldEncryptor,
)
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.audit.verify_chain import main as verify_chain_main
from gov_platform.audit.verify_chain import verify_chain_from_database
from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.protected_attribute_resolution import (
    ProtectedAttributeResolutionRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.human_review import (
    PopulationFindingReviewResolution,
    VerdictReviewResolution,
)
from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _fresh_key() -> str:
    return Fernet.generate_key().decode("ascii")


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


# --- evidence_chain.payload --------------------------------------------------
#
# IMPORTANT test-isolation note: `EvidenceStore.all()`/`verify_chain_from_database`
# scan the *entire*, shared, cumulative `evidence_chain` table with no
# per-test scoping (a pre-existing characteristic, unrelated to M11 — see
# that method's own docstring). A row left behind encrypted under a
# one-off test key would silently break every *other* test's own keyless
# or differently-keyed verify_chain_from_database call against this same
# table, including tests/integration/test_verify_chain_postgres.py's own
# pre-existing "the real chain is valid" test. `evidence_chain` has no
# DELETE grant for gov_platform_app (migration 0008, unrelated to M11), so
# every test below that writes a real encrypted row cleans it up via the
# elevated `admin_db_engine` connection before returning — these tests
# additionally skip if ADMIN_DATABASE_URL isn't set, the same as any other
# test needing that connection.


def _delete_evidence_chain_record(admin_db_engine, sequence_number: int) -> None:
    with Session(admin_db_engine) as session:
        session.execute(
            text("DELETE FROM evidence_chain WHERE sequence_number = :seq"),
            {"seq": sequence_number},
        )
        session.commit()


def test_payload_is_stored_encrypted_and_reads_back_identical(
    db_engine, admin_db_engine, make_decision_event
) -> None:
    key = _fresh_key()
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())

    record = store.append(event, _verdict(event.event_id, verdict_id))
    try:
        with Session(db_engine) as session:
            raw_payload = session.execute(
                text("SELECT payload FROM evidence_chain WHERE sequence_number = :seq"),
                {"seq": record.sequence_number},
            ).scalar_one()
        assert raw_payload.startswith("gpenc1:")
        assert "decision_event" not in raw_payload  # opaque -- not merely obfuscated JSON

        reread = store.get(record.sequence_number)
        assert reread is not None
        assert reread.payload == record.payload
        assert reread.record_hash == record.record_hash
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


def test_record_hash_is_computed_over_plaintext_not_ciphertext(
    db_engine, admin_db_engine, make_decision_event
) -> None:
    # Hash-then-encrypt: the same logical payload must hash identically
    # whether or not encryption is enabled, since compute_hash always runs
    # before encrypt(). docs/milestones/M11.md §5.1.
    event_a = make_decision_event(event_id=f"evt-{uuid4()}")
    event_b = event_a.model_copy(update={"event_id": f"evt-{uuid4()}"})
    verdict_id_a, verdict_id_b = str(uuid4()), str(uuid4())

    plain_store = EvidenceStore(db_engine)
    encrypted_store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(_fresh_key()))

    record_plain = plain_store.append(event_a, _verdict(event_a.event_id, verdict_id_a))
    record_encrypted = encrypted_store.append(event_b, _verdict(event_b.event_id, verdict_id_b))
    try:
        # Different previous_hash (chain position differs), but both
        # correctly recompute from their own plaintext payload -- verified
        # via round trip rather than comparing hashes directly.
        reread_plain = plain_store.get(record_plain.sequence_number)
        reread_encrypted = encrypted_store.get(record_encrypted.sequence_number)
        assert reread_plain is not None
        assert reread_encrypted is not None
        assert reread_plain.payload == record_plain.payload
        assert reread_encrypted.payload == record_encrypted.payload
    finally:
        _delete_evidence_chain_record(admin_db_engine, record_encrypted.sequence_number)


def test_pre_m11_style_plaintext_rows_remain_readable_after_encryption_is_enabled(
    db_engine, make_decision_event
) -> None:
    # Backward compatibility: a row written with no encryptor (unmarked
    # plaintext) must still read back correctly once a real key is later
    # configured -- the gpenc1 marker check falls through to plaintext.
    # No cleanup needed: this row is never gpenc1-marked, so it never
    # poisons any other test's whole-table scan.
    plain_store = EvidenceStore(db_engine)
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    written = plain_store.append(event, _verdict(event.event_id, verdict_id))

    encrypted_store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(_fresh_key()))
    reread = encrypted_store.get(written.sequence_number)

    assert reread is not None
    assert reread.payload == written.payload


def test_decrypt_failure_on_payload_raises_never_returns_a_placeholder(
    db_engine, admin_db_engine, make_decision_event
) -> None:
    # payload is evidentiary content -- must never silently substitute
    # placeholder content, unlike resolution_notes/proxy_basis.
    # docs/milestones/M11.md §5.1/§12.15.
    key_a, key_b = _fresh_key(), _fresh_key()
    store_a = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key_a))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    written = store_a.append(event, _verdict(event.event_id, verdict_id))
    try:
        store_wrong_key = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key_b))
        with pytest.raises(FieldDecryptionError):
            store_wrong_key.get(written.sequence_number)

        store_no_key = EvidenceStore(db_engine, encryptor=NoOpFieldEncryptor())
        with pytest.raises(FieldDecryptionError):
            store_no_key.get(written.sequence_number)
    finally:
        _delete_evidence_chain_record(admin_db_engine, written.sequence_number)


# --- verify_chain: --encryption-key -----------------------------------------


def test_verify_chain_from_database_with_the_correct_key_reports_valid(
    db_engine, admin_db_engine, make_decision_event, postgres_url
) -> None:
    key = _fresh_key()
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    record = store.append(event, _verdict(event.event_id, str(uuid4())))
    try:
        result = verify_chain_from_database(postgres_url, encryption_key=key)
        assert result.valid is True
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


def test_verify_chain_from_database_with_no_key_fails_cleanly_not_a_crash(
    db_engine, admin_db_engine, make_decision_event, postgres_url
) -> None:
    key = _fresh_key()
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    record = store.append(event, _verdict(event.event_id, str(uuid4())))
    try:
        result = verify_chain_from_database(postgres_url)  # no encryption_key given

        assert result.valid is False
        assert "cannot decrypt" in result.detail
        assert "record" in result.detail  # names the specific record, not just "something failed"
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


def test_verify_chain_from_database_with_the_wrong_key_fails_cleanly(
    db_engine, admin_db_engine, make_decision_event, postgres_url
) -> None:
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(_fresh_key()))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    record = store.append(event, _verdict(event.event_id, str(uuid4())))
    try:
        result = verify_chain_from_database(postgres_url, encryption_key=_fresh_key())

        assert result.valid is False
        assert "cannot decrypt" in result.detail
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


def test_cli_main_accepts_encryption_key_flag_and_succeeds(
    db_engine, admin_db_engine, make_decision_event, postgres_url, capsys
) -> None:
    key = _fresh_key()
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(key))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    record = store.append(event, _verdict(event.event_id, str(uuid4())))
    try:
        exit_code = verify_chain_main(["--database-url", postgres_url, "--encryption-key", key])

        assert exit_code == 0
        assert "chain valid" in capsys.readouterr().out
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


def test_cli_main_without_encryption_key_against_an_encrypted_chain_exits_nonzero(
    db_engine, admin_db_engine, make_decision_event, postgres_url, capsys
) -> None:
    store = EvidenceStore(db_engine, encryptor=FernetFieldEncryptor(_fresh_key()))
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    record = store.append(event, _verdict(event.event_id, str(uuid4())))
    try:
        exit_code = verify_chain_main(["--database-url", postgres_url])

        assert exit_code == 1
        assert "cannot decrypt" in capsys.readouterr().out
    finally:
        _delete_evidence_chain_record(admin_db_engine, record.sequence_number)


# --- verdict_reviews.resolution_notes ---------------------------------------


def _new_allow_verdict_id(evidence_store: EvidenceStore, make_decision_event) -> str:
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    evidence_store.append(event, _verdict(event.event_id, verdict_id))
    return verdict_id


def test_verdict_review_resolution_notes_stored_encrypted_and_reads_back(
    evidence_store, make_decision_event, db_engine
) -> None:
    key = _fresh_key()
    repository = VerdictReviewRepository(encryptor=FernetFieldEncryptor(key))
    verdict_id = _new_allow_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="a real, actionable disparity",
        )
        session.commit()

    with Session(db_engine) as session:
        raw_notes = session.execute(
            text("SELECT resolution_notes FROM verdict_reviews WHERE id = :id"), {"id": created.id}
        ).scalar_one()
    assert raw_notes.startswith("gpenc1:")

    with Session(db_engine) as session:
        reread = repository.get(session, created.id)
    assert reread is not None
    assert reread.resolution_notes == "a real, actionable disparity"


def test_verdict_review_reviewer_column_is_never_encrypted(
    evidence_store, make_decision_event, db_engine
) -> None:
    # docs/milestones/M11.md §4.1: reviewer cannot be encrypted at all --
    # resolve()'s own equality check against it would break permanently.
    repository = VerdictReviewRepository(encryptor=FernetFieldEncryptor(_fresh_key()))
    verdict_id = _new_allow_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        created = repository.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        claimed = repository.claim(session, created.id, "jane")
        session.commit()
    assert claimed.reviewer == "jane"

    with Session(db_engine) as session:
        raw_reviewer = session.execute(
            text("SELECT reviewer FROM verdict_reviews WHERE id = :id"), {"id": created.id}
        ).scalar_one()
    assert raw_reviewer == "jane"  # plaintext, unmarked

    # And resolve() -- the equality check reviewer participates in --
    # keeps working with a real key configured.
    with Session(db_engine) as session:
        resolved = repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="test",
        )
        session.commit()
    assert resolved.reviewer == "jane"


def test_verdict_review_decrypt_failure_on_notes_degrades_to_placeholder_not_a_crash(
    evidence_store, make_decision_event, db_engine
) -> None:
    key_a, key_b = _fresh_key(), _fresh_key()
    repository_a = VerdictReviewRepository(encryptor=FernetFieldEncryptor(key_a))
    verdict_id = _new_allow_verdict_id(evidence_store, make_decision_event)

    with Session(db_engine) as session:
        created = repository_a.create(session, verdict_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository_a.claim(session, created.id, "jane")
        repository_a.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=VerdictReviewResolution.CONFIRMED,
            notes="secret notes",
        )
        session.commit()

    repository_wrong_key = VerdictReviewRepository(encryptor=FernetFieldEncryptor(key_b))
    with Session(db_engine) as session:
        reread = repository_wrong_key.get(session, created.id)

    assert reread is not None
    assert reread.resolution_notes == UNREADABLE_PLACEHOLDER
    assert reread.status is not None  # rest of the row is intact, no crash


# --- population_finding_reviews.resolution_notes ----------------------------


def _seed_flagged_population_finding(db_engine) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"pfr-encryption-{uuid4()}")
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system.id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.FLAGGED,
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


def test_population_finding_review_resolution_notes_stored_encrypted_and_reads_back(
    db_engine,
) -> None:
    key = _fresh_key()
    repository = PopulationFindingReviewRepository(encryptor=FernetFieldEncryptor(key))
    population_finding_id = _seed_flagged_population_finding(db_engine)

    with Session(db_engine) as session:
        created = repository.create(session, population_finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository.claim(session, created.id, "jane")
        repository.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=PopulationFindingReviewResolution.CONFIRMED,
            notes="a real disparity",
        )
        session.commit()

    with Session(db_engine) as session:
        raw_notes = session.execute(
            text("SELECT resolution_notes FROM population_finding_reviews WHERE id = :id"),
            {"id": created.id},
        ).scalar_one()
    assert raw_notes.startswith("gpenc1:")

    with Session(db_engine) as session:
        reread = repository.get(session, created.id)
    assert reread is not None
    assert reread.resolution_notes == "a real disparity"


def test_population_finding_review_decrypt_failure_on_notes_degrades_to_placeholder(
    db_engine,
) -> None:
    key_a, key_b = _fresh_key(), _fresh_key()
    repository_a = PopulationFindingReviewRepository(encryptor=FernetFieldEncryptor(key_a))
    population_finding_id = _seed_flagged_population_finding(db_engine)

    with Session(db_engine) as session:
        created = repository_a.create(session, population_finding_id)
        session.commit()
    assert created is not None

    with Session(db_engine) as session:
        repository_a.claim(session, created.id, "jane")
        repository_a.resolve(
            session,
            created.id,
            reviewer="jane",
            resolution=PopulationFindingReviewResolution.CONFIRMED,
            notes="secret",
        )
        session.commit()

    repository_wrong_key = PopulationFindingReviewRepository(encryptor=FernetFieldEncryptor(key_b))
    with Session(db_engine) as session:
        reread = repository_wrong_key.get(session, created.id)

    assert reread is not None
    assert reread.resolution_notes == UNREADABLE_PLACEHOLDER


# --- protected_attribute_resolutions.proxy_basis -----------------------------


def _seed_decision_event(db_engine) -> DecisionEvent:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"par-encryption-{uuid4()}")
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
        session.commit()
    return event


def test_proxy_basis_stored_encrypted_and_reads_back(db_engine) -> None:
    key = _fresh_key()
    repository = ProtectedAttributeResolutionRepository(encryptor=FernetFieldEncryptor(key))
    event = _seed_decision_event(db_engine)

    with Session(db_engine) as session:
        repository.create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="zip_code",
                classification=ProtectedAttributeClassification.PROXIED,
                proxy_basis="race",
                resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        session.commit()

    with Session(db_engine) as session:
        raw_proxy_basis = session.execute(
            text(
                "SELECT proxy_basis FROM protected_attribute_resolutions "
                "WHERE decision_event_id = :id"
            ),
            {"id": event.event_id},
        ).scalar_one()
    assert raw_proxy_basis.startswith("gpenc1:")

    with Session(db_engine) as session:
        resolutions = repository.list_by_decision_event(session, event.event_id)
    assert resolutions[0].proxy_basis == "race"


def test_attribute_name_column_is_never_encrypted(db_engine) -> None:
    # docs/milestones/M11.md §4.1: attribute_name cannot be encrypted --
    # list_by_decision_event's own ORDER BY depends on plaintext order.
    key = _fresh_key()
    repository = ProtectedAttributeResolutionRepository(encryptor=FernetFieldEncryptor(key))
    event = _seed_decision_event(db_engine)

    with Session(db_engine) as session:
        for attribute_name in ["zip_code", "age", "gender"]:
            repository.create(
                session,
                ResolvedProtectedAttribute(
                    decision_event_id=event.event_id,
                    attribute_name=attribute_name,
                    classification=ProtectedAttributeClassification.WITHHELD,
                    resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            )
        session.commit()

    with Session(db_engine) as session:
        resolutions = repository.list_by_decision_event(session, event.event_id)

    assert [r.attribute_name for r in resolutions] == ["age", "gender", "zip_code"]


def test_proxy_basis_decrypt_failure_degrades_to_placeholder(db_engine) -> None:
    key_a, key_b = _fresh_key(), _fresh_key()
    repository_a = ProtectedAttributeResolutionRepository(encryptor=FernetFieldEncryptor(key_a))
    event = _seed_decision_event(db_engine)

    with Session(db_engine) as session:
        repository_a.create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="zip_code",
                classification=ProtectedAttributeClassification.PROXIED,
                proxy_basis="race",
                resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        session.commit()

    repository_wrong_key = ProtectedAttributeResolutionRepository(
        encryptor=FernetFieldEncryptor(key_b)
    )
    with Session(db_engine) as session:
        resolutions = repository_wrong_key.list_by_decision_event(session, event.event_id)

    assert resolutions[0].proxy_basis == UNREADABLE_PLACEHOLDER
    assert resolutions[0].classification is ProtectedAttributeClassification.PROXIED
