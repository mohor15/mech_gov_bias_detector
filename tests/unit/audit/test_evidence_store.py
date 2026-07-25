from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from gov_platform.audit.evidence_store import GENESIS_HASH, EvidenceStore
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus

_CONCURRENT_WRITERS = 20


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


def test_first_record_chains_from_genesis(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event()
    record = evidence_store.append(event, _verdict(event.event_id, "verd-001"))

    assert record.sequence_number == 1
    assert record.previous_hash == GENESIS_HASH
    assert len(record.record_hash) == 64
    assert record.record_hash != GENESIS_HASH


def test_second_record_chains_from_first(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event()
    first = evidence_store.append(event, _verdict(event.event_id, "verd-001"))
    second = evidence_store.append(event, _verdict(event.event_id, "verd-002"))

    assert second.sequence_number == 2
    assert second.previous_hash == first.record_hash
    assert second.record_hash != first.record_hash


def test_record_hash_is_deterministic_given_same_content(
    evidence_db_path: Path, make_decision_event
) -> None:
    # Same content appended to two independent, freshly-genesis-ed stores
    # must produce the same hash — the chain is a pure function of content
    # plus prior hash, not of wall-clock time or process identity.
    event = make_decision_event()
    verdict = _verdict(event.event_id, "verd-001")

    store_a = EvidenceStore(evidence_db_path.parent / "a.db")
    store_b = EvidenceStore(evidence_db_path.parent / "b.db")

    record_a = store_a.append(event, verdict)
    record_b = store_b.append(event, verdict)

    assert record_a.record_hash == record_b.record_hash


def test_evidence_store_has_no_mutation_methods(evidence_store: EvidenceStore) -> None:
    # Application-layer append-only enforcement for M0 (see module docstring):
    # this is a structural assertion that the class exposes no way to edit
    # or remove a record, not a database-privilege test (that's M1).
    public_methods = {name for name in dir(evidence_store) if not name.startswith("_")}
    assert public_methods == {"append", "get", "all"}


def test_get_returns_none_for_missing_sequence(evidence_store: EvidenceStore) -> None:
    assert evidence_store.get(999) is None


def test_get_returns_the_matching_record(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event()
    appended = evidence_store.append(event, _verdict(event.event_id, "verd-001"))

    fetched = evidence_store.get(appended.sequence_number)

    assert fetched is not None
    assert fetched.record_hash == appended.record_hash
    assert fetched.decision_event_id == event.event_id


def test_all_returns_records_in_sequence_order(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event()
    evidence_store.append(event, _verdict(event.event_id, "verd-001"))
    evidence_store.append(event, _verdict(event.event_id, "verd-002"))

    records = evidence_store.all()

    assert [r.sequence_number for r in records] == [1, 2]


def test_payload_round_trips_verdict_status(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event()
    record = evidence_store.append(event, _verdict(event.event_id, "verd-001"))

    assert record.payload["verdict"]["status"] == "ALLOW"
    assert record.payload["decision_event"]["event_id"] == event.event_id


def test_concurrent_appends_produce_a_single_valid_chain(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    # Substantiates the module docstring's concurrency claim: N threads
    # appending at once must still serialize into one unbroken, gapless
    # chain — not just "not crash." Added during the M0 finalization review
    # because the claim previously had no test behind it.
    event = make_decision_event()

    def _write(index: int) -> None:
        evidence_store.append(event, _verdict(event.event_id, f"verd-{index}"))

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(_CONCURRENT_WRITERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = evidence_store.all()

    assert len(records) == _CONCURRENT_WRITERS
    assert [r.sequence_number for r in records] == list(range(1, _CONCURRENT_WRITERS + 1))
    assert records[0].previous_hash == GENESIS_HASH
    for earlier, later in zip(records, records[1:]):  # noqa: B905 — intentionally unequal-length pairwise iteration
        assert later.previous_hash == earlier.record_hash
    assert len({r.record_hash for r in records}) == _CONCURRENT_WRITERS
