"""`verify_chain` is pure — no DB — so corruption detection is fully
testable locally with hand-built `EvidenceRecord` fixtures, including the
"a standalone chain-verification job detects a deliberately corrupted row"
M1 acceptance criterion, verified here without needing Postgres at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.audit.evidence_store import EvidenceRecord
from gov_platform.audit.hash_chain import GENESIS_HASH, canonical_json, compute_hash
from gov_platform.audit.verify_chain import verify_chain

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _record(sequence_number: int, payload: dict[str, object], previous_hash: str) -> EvidenceRecord:
    payload_json = canonical_json(payload)
    return EvidenceRecord(
        sequence_number=sequence_number,
        decision_event_id=f"evt-{sequence_number}",
        verdict_id=f"verd-{sequence_number}",
        payload=payload,
        previous_hash=previous_hash,
        record_hash=compute_hash(previous_hash, payload_json),
        recorded_at=_NOW,
    )


def _valid_chain(length: int) -> list[EvidenceRecord]:
    records = []
    previous_hash = GENESIS_HASH
    for i in range(1, length + 1):
        record = _record(i, {"n": i}, previous_hash)
        records.append(record)
        previous_hash = record.record_hash
    return records


def test_empty_chain_is_valid() -> None:
    result = verify_chain([])
    assert result.valid is True
    assert result.checked_count == 0


def test_valid_chain_of_several_records() -> None:
    result = verify_chain(_valid_chain(5))
    assert result.valid is True
    assert result.checked_count == 5
    assert result.first_corruption_at is None


def test_detects_tampered_payload() -> None:
    records = _valid_chain(3)
    tampered = records[1].model_copy(update={"payload": {"n": 999}})
    records[1] = tampered

    result = verify_chain(records)

    assert result.valid is False
    assert result.first_corruption_at == 2
    assert result.checked_count == 1  # record 1 verified fine before the break


def test_detects_tampered_previous_hash() -> None:
    records = _valid_chain(3)
    tampered = records[2].model_copy(update={"previous_hash": "f" * 64})
    records[2] = tampered

    result = verify_chain(records)

    assert result.valid is False
    assert result.first_corruption_at == 3


def test_detects_deleted_record_breaking_the_link() -> None:
    records = _valid_chain(3)
    del records[1]  # remove the middle record; record 3's previous_hash no longer matches

    result = verify_chain(records)

    assert result.valid is False
    assert result.first_corruption_at == 3


def test_first_record_must_chain_from_genesis() -> None:
    bad_first = _record(1, {"n": 1}, previous_hash="f" * 64)

    result = verify_chain([bad_first])

    assert result.valid is False
    assert result.first_corruption_at == 1
