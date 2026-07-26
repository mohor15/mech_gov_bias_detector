"""Standalone hash-chain verification — architecture §13, M1.

`verify_chain` is pure: given a sequence of evidence records, it re-derives
each record's hash from its own payload and the previous record's hash, and
reports the first point of disagreement. No database dependency at all —
fully unit-testable locally with hand-built `EvidenceRecord` fixtures,
including deliberately corrupted ones. `verify_chain_from_database` and the
CLI wrapper are the thin, Postgres-dependent shell around that pure core.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import BaseModel

from gov_platform.audit.evidence_store import EvidenceRecord, EvidenceStore
from gov_platform.audit.hash_chain import GENESIS_HASH, canonical_json, compute_hash
from gov_platform.db.session import create_db_engine


class ChainVerificationResult(BaseModel):
    valid: bool
    checked_count: int
    first_corruption_at: int | None = None
    detail: str


def verify_chain(records: Sequence[EvidenceRecord]) -> ChainVerificationResult:
    """Re-derive every record's hash and confirm the chain is unbroken.

    Records must already be in ascending `sequence_number` order — callers
    reading from `EvidenceStore.all()` get that for free.
    """
    expected_previous_hash = GENESIS_HASH

    for index, record in enumerate(records):
        if record.previous_hash != expected_previous_hash:
            return ChainVerificationResult(
                valid=False,
                checked_count=index,
                first_corruption_at=record.sequence_number,
                detail=(
                    f"record {record.sequence_number}: previous_hash mismatch "
                    f"(expected {expected_previous_hash}, found {record.previous_hash})"
                ),
            )

        recomputed_hash = compute_hash(record.previous_hash, canonical_json(record.payload))
        if recomputed_hash != record.record_hash:
            return ChainVerificationResult(
                valid=False,
                checked_count=index,
                first_corruption_at=record.sequence_number,
                detail=(
                    f"record {record.sequence_number}: record_hash does not match its payload "
                    "(payload or record_hash was altered after the fact)"
                ),
            )

        expected_previous_hash = record.record_hash

    return ChainVerificationResult(valid=True, checked_count=len(records), detail="chain valid")


def verify_chain_from_database(database_url: str) -> ChainVerificationResult:
    engine = create_db_engine(database_url)
    store = EvidenceStore(engine)
    return verify_chain(store.all())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the evidence hash chain end to end.")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args(argv)

    result = verify_chain_from_database(args.database_url)
    print(f"checked {result.checked_count} record(s): {result.detail}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
