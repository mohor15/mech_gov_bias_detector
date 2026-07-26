"""Postgres-backed, hash-chained Evidence Store — architecture §13, M1.

M0 shipped this as one SQLite table holding a full JSON blob per record.
M1 replaces the internals entirely (constructor, storage, concurrency
mechanism) while preserving the exact public surface — `append`, `get`,
`all`, and the `EvidenceRecord` shape — so every caller (the ingestion
route, `api.dependencies`) needed zero changes. See docs/milestones/M1.md
for the full reasoning; the short version:

* **Normalized, not blob-only.** `append` now writes through five
  repositories (System, ModelVersion, DecisionEvent, Finding, Verdict) in
  one transaction, in addition to the hash-chained `evidence_chain` row —
  the operational store architecture §16 calls for, not just an audit blob.
* **Concurrency**: M0 used an in-process `threading.Lock`, explicitly
  documented as a placeholder ("the real fix is Postgres transaction
  isolation, M1's job"). M1 delivers that fix via `pg_advisory_xact_lock`,
  which correctly serializes the read-latest-hash-then-insert sequence
  across concurrent transactions *and* across multiple app instances/
  processes — something no in-process lock could ever provide. Table-row
  locking (`SELECT ... FOR UPDATE`) was considered and rejected: Postgres
  requires UPDATE privilege to take that lock, which would have defeated
  the `REVOKE UPDATE` this table depends on for append-only enforcement.
* **Append-only** is now enforced at the database-privilege level
  (`infra/migrations/0008_grant_evidence_chain_privileges.sql`), not just
  by this class exposing no update/delete method (M0's application-layer-
  only stopgap).
* **No eager connection.** `EvidenceStore.__init__` does no I/O — it stores
  the injected `Engine` and constructs its repositories, nothing more.
  SQLAlchemy engines are lazy; this means an app that never successfully
  completes an ingestion (e.g. most of M0's composition-root and middleware
  tests) never needs a live database at all. Schema creation is
  `db.migrate`'s job now, not this constructor's — see the M1 design note
  on why that matters for M0's tests staying runnable without Postgres.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.audit.hash_chain import GENESIS_HASH, canonical_json, compute_hash
from gov_platform.db.models import EvidenceChainRow
from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.finding import FindingRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.model_version import UNSPECIFIED_VERSION
from gov_platform.schemas.verdict import GovernanceVerdict

# Arbitrary, stable key identifying "the evidence chain append critical
# section" to Postgres's advisory-lock registry. Any fixed 64-bit integer
# works; it need not mean anything beyond being unique to this purpose.
_ADVISORY_LOCK_KEY = 913_411_007


class EvidenceRecord(BaseModel):
    """Read-facing view of a persisted evidence record. Unchanged from M0."""

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

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._system_repo = SystemRepository()
        self._model_version_repo = ModelVersionRepository()
        self._decision_event_repo = DecisionEventRepository()
        self._finding_repo = FindingRepository()
        self._verdict_repo = VerdictRepository(self._finding_repo)

    def append(self, decision_event: DecisionEvent, verdict: GovernanceVerdict) -> EvidenceRecord:
        """Persist one Decision Event + Verdict pair, atomically, as the
        next chain link — normalized operational rows and the hash-chained
        evidence row together, in one transaction."""
        payload: dict[str, Any] = {
            "decision_event": decision_event.model_dump(mode="json"),
            "verdict": verdict.model_dump(mode="json"),
        }
        payload_json = canonical_json(payload)

        with Session(self._engine) as session:
            # Serializes concurrent appends across processes — see module
            # docstring. Held for the rest of this transaction, released
            # automatically on commit/rollback.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})

            system = self._system_repo.get_or_create_by_name(session, decision_event.system_id)
            model_version = self._model_version_repo.get_or_create(
                session, system_id=system.id, version=UNSPECIFIED_VERSION
            )
            self._decision_event_repo.create(
                session, decision_event, model_version_id=model_version.id
            )
            for finding in verdict.findings:
                self._finding_repo.create(session, finding)
            self._verdict_repo.create(session, verdict)

            previous_hash = self._latest_hash(session)
            record_hash = compute_hash(previous_hash, payload_json)
            recorded_at = datetime.now(UTC)

            chain_row = EvidenceChainRow(
                decision_event_id=decision_event.event_id,
                verdict_id=verdict.verdict_id,
                payload=payload_json,
                previous_hash=previous_hash,
                record_hash=record_hash,
                recorded_at=recorded_at,
            )
            session.add(chain_row)
            session.commit()
            session.refresh(chain_row)

            return EvidenceRecord(
                sequence_number=chain_row.sequence_number,
                decision_event_id=chain_row.decision_event_id,
                verdict_id=chain_row.verdict_id,
                payload=payload,
                previous_hash=chain_row.previous_hash,
                record_hash=chain_row.record_hash,
                recorded_at=chain_row.recorded_at,
            )

    def get(self, sequence_number: int) -> EvidenceRecord | None:
        with Session(self._engine) as session:
            row = session.get(EvidenceChainRow, sequence_number)
            return self._to_model(row) if row is not None else None

    def all(self) -> list[EvidenceRecord]:
        """Return every record, unbounded — see M0's deferred-to-M1 note on
        pagination. Formalizing that remains out of M1's own scope too;
        nothing here narrowed it further than M0 already flagged."""
        with Session(self._engine) as session:
            statement = select(EvidenceChainRow).order_by(EvidenceChainRow.sequence_number)
            rows = session.execute(statement).scalars()
            return [self._to_model(row) for row in rows]

    def _latest_hash(self, session: Session) -> str:
        latest = session.execute(
            select(EvidenceChainRow).order_by(EvidenceChainRow.sequence_number.desc()).limit(1)
        ).scalar_one_or_none()
        return latest.record_hash if latest is not None else GENESIS_HASH

    @staticmethod
    def _to_model(row: EvidenceChainRow) -> EvidenceRecord:
        return EvidenceRecord(
            sequence_number=row.sequence_number,
            decision_event_id=row.decision_event_id,
            verdict_id=row.verdict_id,
            payload=json.loads(row.payload),
            previous_hash=row.previous_hash,
            record_hash=row.record_hash,
            recorded_at=row.recorded_at,
        )
