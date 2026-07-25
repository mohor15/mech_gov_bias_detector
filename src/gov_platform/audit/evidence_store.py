"""SQLite-backed, hash-chained Evidence Store — architecture §13, M0 scope.

Each record's ``record_hash`` covers its own payload *and* the previous
record's hash (``sha256(previous_hash : canonical_json(payload))``), exactly
as architecture §13.1 specifies, so any retroactive edit of an older record
would break every hash after it. That property is real starting today, not
simulated — M1 adds a standalone verification job and Postgres-level
immutability, it does not add the hashing itself.

Two things are deliberately *not* here, and are called out rather than
silently deferred:

* **Append-only is enforced at the application layer only.** This class
  simply exposes no update/delete method. A DB user with direct SQLite file
  access could still tamper with the file. Enforcing this at the
  database-privilege level requires Postgres GRANT/REVOKE, which is M1.
* **Concurrency**: a ``threading.Lock`` serializes the read-last-hash /
  compute / insert sequence within this process, which is sufficient for the
  M0 walking skeleton (a single-process app). It does not provide any
  cross-process or multi-replica ordering guarantee — that is a Postgres
  transaction-isolation concern for M1 and a deployment-topology concern for
  M13, not something SQLite plus an in-process lock can promise. This is
  covered by a concurrency test (see ``test_evidence_store.py``), added
  during the M0 finalization review so the serialization claim above is
  verified, not just asserted in a comment.
* **No encryption at rest.** Evidence payloads — including
  ``protected_attribute_refs`` values — are stored as plaintext JSON in the
  SQLite file. Do not point this milestone at real applicant data. Encryption
  at rest, retention tiers, and privilege classification are M11 scope
  (architecture §13.2).
* **`all()` is unbounded** — it loads every record into memory with no
  pagination. Fine at M0's data volumes; revisit alongside the M1 Postgres
  migration and whatever real query API M1/M11 introduces, not before —
  adding pagination to a SQLite method that M1 is about to replace would be
  wasted work.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.verdict import GovernanceVerdict

GENESIS_HASH = "0" * 64


def _canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic serialization so the same content always hashes the same way."""
    return json.dumps(payload, sort_keys=True, default=str)


def _compute_hash(previous_hash: str, payload_json: str) -> str:
    digest = hashlib.sha256(f"{previous_hash}:{payload_json}".encode())
    return digest.hexdigest()


class _Base(DeclarativeBase):
    pass


class _EvidenceRecordORM(_Base):
    __tablename__ = "evidence_records"

    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_event_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    verdict_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecord(BaseModel):
    """Read-facing view of a persisted evidence record."""

    model_config = ConfigDict(frozen=True)

    sequence_number: int
    decision_event_id: str
    verdict_id: str
    payload: dict[str, Any]
    previous_hash: str
    record_hash: str
    recorded_at: datetime


class EvidenceStore:
    """Append-only, hash-chained ledger of governed Decision Events."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = create_engine(f"sqlite:///{db_path}")
        self._lock = threading.Lock()
        _Base.metadata.create_all(self._engine)

    def append(self, decision_event: DecisionEvent, verdict: GovernanceVerdict) -> EvidenceRecord:
        """Persist one Decision Event + Verdict pair as the next chain link."""
        payload: dict[str, Any] = {
            "decision_event": decision_event.model_dump(mode="json"),
            "verdict": verdict.model_dump(mode="json"),
        }
        payload_json = _canonical_json(payload)

        with self._lock, Session(self._engine) as session:
            previous_hash = self._latest_hash(session)
            record_hash = _compute_hash(previous_hash, payload_json)
            recorded_at = datetime.now(UTC)

            orm_record = _EvidenceRecordORM(
                decision_event_id=decision_event.event_id,
                verdict_id=verdict.verdict_id,
                payload=payload_json,
                previous_hash=previous_hash,
                record_hash=record_hash,
                recorded_at=recorded_at,
            )
            session.add(orm_record)
            session.commit()
            session.refresh(orm_record)

            return EvidenceRecord(
                sequence_number=orm_record.sequence_number,
                decision_event_id=orm_record.decision_event_id,
                verdict_id=orm_record.verdict_id,
                payload=payload,
                previous_hash=orm_record.previous_hash,
                record_hash=orm_record.record_hash,
                recorded_at=orm_record.recorded_at,
            )

    def get(self, sequence_number: int) -> EvidenceRecord | None:
        with Session(self._engine) as session:
            orm_record = session.get(_EvidenceRecordORM, sequence_number)
            if orm_record is None:
                return None
            return self._to_model(orm_record)

    def all(self) -> list[EvidenceRecord]:
        """Return every record, unbounded — see module docstring caveats."""
        with Session(self._engine) as session:
            statement = select(_EvidenceRecordORM).order_by(_EvidenceRecordORM.sequence_number)
            rows = session.execute(statement).scalars()
            return [self._to_model(row) for row in rows]

    def _latest_hash(self, session: Session) -> str:
        latest = session.execute(
            select(_EvidenceRecordORM).order_by(_EvidenceRecordORM.sequence_number.desc()).limit(1)
        ).scalar_one_or_none()
        return latest.record_hash if latest is not None else GENESIS_HASH

    @staticmethod
    def _to_model(orm_record: _EvidenceRecordORM) -> EvidenceRecord:
        return EvidenceRecord(
            sequence_number=orm_record.sequence_number,
            decision_event_id=orm_record.decision_event_id,
            verdict_id=orm_record.verdict_id,
            payload=json.loads(orm_record.payload),
            previous_hash=orm_record.previous_hash,
            record_hash=orm_record.record_hash,
            recorded_at=orm_record.recorded_at,
        )
