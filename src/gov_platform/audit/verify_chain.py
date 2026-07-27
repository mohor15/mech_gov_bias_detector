"""Standalone hash-chain verification — architecture §13, M1. M5: optional
signature verification.

`verify_chain` is pure: given a sequence of evidence records, it re-derives
each record's hash from its own payload and the previous record's hash, and
reports the first point of disagreement. No database dependency at all —
fully unit-testable locally with hand-built `EvidenceRecord` fixtures,
including deliberately corrupted ones. `verify_chain_from_database` and the
CLI wrapper are the thin, Postgres-dependent shell around that pure core.

M5: given a public key, each record's signature is also checked against
its `record_hash` (`audit/signing.py`) — a genuinely different guarantee
than the hash chain alone provides (see that module's docstring).
Records with no signature (written before M5) are skipped, not failed —
signing applies going forward only, see `schemas/verdict.py`'s docstring.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import BaseModel

from gov_platform.audit.evidence_store import EvidenceRecord, EvidenceStore
from gov_platform.audit.hash_chain import GENESIS_HASH, canonical_json, compute_hash
from gov_platform.audit.signing import verify_signature
from gov_platform.db.session import create_db_engine


class ChainVerificationResult(BaseModel):
    valid: bool
    checked_count: int
    first_corruption_at: int | None = None
    detail: str


def verify_chain(
    records: Sequence[EvidenceRecord], *, public_key_hex: str | None = None
) -> ChainVerificationResult:
    """Re-derive every record's hash and confirm the chain is unbroken.
    When `public_key_hex` is given, also verify each signed record's
    signature against it.

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

        if (
            public_key_hex is not None
            and record.signature is not None
            and not verify_signature(record.record_hash, record.signature, public_key_hex)
        ):
            return ChainVerificationResult(
                valid=False,
                checked_count=index,
                first_corruption_at=record.sequence_number,
                detail=(
                    f"record {record.sequence_number}: signature does not verify against "
                    "the provided public key"
                ),
            )

        expected_previous_hash = record.record_hash

    return ChainVerificationResult(valid=True, checked_count=len(records), detail="chain valid")


def verify_chain_from_database(
    database_url: str, *, public_key_hex: str | None = None
) -> ChainVerificationResult:
    engine = create_db_engine(database_url)
    store = EvidenceStore(engine)
    return verify_chain(store.all(), public_key_hex=public_key_hex)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the evidence hash chain end to end.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--public-key",
        required=False,
        help="Hex-encoded Ed25519 public key to also verify signatures against "
        "(see `python -m gov_platform.audit.signing --private-key ...`). "
        "Omit to check only the hash chain.",
    )
    args = parser.parse_args(argv)

    result = verify_chain_from_database(args.database_url, public_key_hex=args.public_key)
    print(f"checked {result.checked_count} record(s): {result.detail}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
