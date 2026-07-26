"""EvidenceStore's behavioral tests, against a real Postgres — CI-only (see
conftest.requires_postgres). Supersedes M0's SQLite-backed
`test_evidence_store.py`; the pure hash-chain assertions that don't need a
DB live in `tests/unit/audit/test_hash_chain.py` instead.

Assertions here are deliberately *relative*, not absolute (no
`sequence_number == 1` / `previous_hash == GENESIS_HASH`): this table is
shared across the whole CI run with no truncation between tests — by
design, evidence_chain is the one table nothing (not even the app's own
DB role) can delete from. Capturing "state before" and asserting the new
record is consistent with it is not a weaker test than M0's fresh-SQLite-
file version; it's a more correct one for a table that, like the real
system, never resets. Every test also uses a unique event_id: `decision_events.id`
is a hard primary key now (a deliberate new constraint — see EvidenceStore's
module docstring), so reusing "evt-001" across tests would collide.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres

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


def _unique_event_id() -> str:
    return f"evt-{uuid4()}"


def test_append_chains_from_whatever_the_current_tail_is(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    tail_before = evidence_store.all()
    expected_previous_hash = tail_before[-1].record_hash if tail_before else "0" * 64

    event = make_decision_event(event_id=_unique_event_id())
    record = evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    assert record.sequence_number == len(tail_before) + 1
    assert record.previous_hash == expected_previous_hash
    assert len(record.record_hash) == 64


def test_second_append_chains_from_first(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event(event_id=_unique_event_id())
    first = evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    event_2 = make_decision_event(event_id=_unique_event_id())
    second = evidence_store.append(event_2, _verdict(event_2.event_id, str(uuid4())))

    assert second.sequence_number == first.sequence_number + 1
    assert second.previous_hash == first.record_hash
    assert second.record_hash != first.record_hash


def test_duplicate_event_id_is_rejected(evidence_store: EvidenceStore, make_decision_event) -> None:
    # New in M1: decision_events.id (= DecisionEvent.event_id) is a real
    # primary key. Re-ingesting the same event_id is a data-integrity
    # error now, not a silently-accepted duplicate (see repository docstring).
    event_id = _unique_event_id()
    event = make_decision_event(event_id=event_id)
    evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    with pytest.raises(IntegrityError):
        evidence_store.append(event, _verdict(event.event_id, str(uuid4())))


def test_get_returns_none_for_a_never_used_sequence_number(evidence_store: EvidenceStore) -> None:
    assert evidence_store.get(2_147_483_647) is None


def test_get_returns_the_matching_record(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event(event_id=_unique_event_id())
    appended = evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    fetched = evidence_store.get(appended.sequence_number)

    assert fetched is not None
    assert fetched.record_hash == appended.record_hash
    assert fetched.decision_event_id == event.event_id


def test_payload_round_trips_verdict_status(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    event = make_decision_event(event_id=_unique_event_id())
    record = evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    assert record.payload["verdict"]["status"] == "ALLOW"
    assert record.payload["decision_event"]["event_id"] == event.event_id


def test_system_is_auto_provisioned_and_reused_by_name(
    evidence_store: EvidenceStore, make_decision_event, db_engine
) -> None:
    from sqlalchemy.orm import Session

    from gov_platform.db.repositories.system import SystemRepository

    system_name = f"system-{uuid4()}"
    event_1 = make_decision_event(event_id=_unique_event_id(), system_id=system_name)
    event_2 = make_decision_event(event_id=_unique_event_id(), system_id=system_name)

    evidence_store.append(event_1, _verdict(event_1.event_id, str(uuid4())))
    evidence_store.append(event_2, _verdict(event_2.event_id, str(uuid4())))

    with Session(db_engine) as session:
        system = SystemRepository().get_by_name(session, system_name)

    assert system is not None
    # Second ingest reused the same System row rather than creating a
    # duplicate — this is the acceptance criterion from the M1 milestone
    # card, exercised via auto-provisioning rather than explicit
    # pre-registration (see EvidenceStore's module docstring).


def test_concurrent_appends_produce_one_unbroken_chain(
    evidence_store: EvidenceStore, make_decision_event
) -> None:
    tail_before = evidence_store.all()
    starting_sequence = len(tail_before) + 1
    starting_previous_hash = tail_before[-1].record_hash if tail_before else "0" * 64

    def _write() -> None:
        event = make_decision_event(event_id=_unique_event_id())
        evidence_store.append(event, _verdict(event.event_id, str(uuid4())))

    threads = [threading.Thread(target=_write) for _ in range(_CONCURRENT_WRITERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    all_records = evidence_store.all()
    new_records = [r for r in all_records if r.sequence_number >= starting_sequence]

    assert len(new_records) == _CONCURRENT_WRITERS
    assert [r.sequence_number for r in new_records] == list(
        range(starting_sequence, starting_sequence + _CONCURRENT_WRITERS)
    )
    assert new_records[0].previous_hash == starting_previous_hash
    for earlier, later in zip(new_records, new_records[1:]):  # noqa: B905
        assert later.previous_hash == earlier.record_hash
    assert len({r.record_hash for r in new_records}) == _CONCURRENT_WRITERS
