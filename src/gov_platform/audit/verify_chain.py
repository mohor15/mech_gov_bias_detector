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

M11 (architecture §13): given an `--encryption-key`, `verify_chain_from_database`
constructs its own `EvidenceStore` with a real `FieldEncryptor`
(`audit/encryption.py`), so `store.all()` can decrypt `payload` before this
module's hash-recomputation logic ever sees it — that logic itself needs
no change, since it already operates on the decrypted
`EvidenceRecord.payload` dict, never on raw column bytes. If `store.all()`
raises `FieldDecryptionError` (no key given, the wrong key, or corrupted
ciphertext), that is caught here and reported as its own, distinct
`ChainVerificationResult` — clearly worded to distinguish "cannot be read"
from an actual hash-mismatch tamper finding — rather than propagating as
an unhandled crash. See `docs/milestones/M11.md` §5.1/§12.5.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import BaseModel

from gov_platform.audit.encryption import FieldDecryptionError, load_encryptor
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
    database_url: str, *, public_key_hex: str | None = None, encryption_key: str | None = None
) -> ChainVerificationResult:
    """`encryption_key` is `Settings.FIELD_ENCRYPTION_KEY`'s own value —
    required whenever the deployment being verified has encryption
    enabled (§5.1/§9): `EvidenceStore` needs it to decrypt `payload`
    before this module's hash-recomputation logic can run at all. Omitting
    it against an encrypted deployment does not crash uncontrolled — it is
    caught below and reported as a clean, distinct `ChainVerificationResult`."""
    engine = create_db_engine(database_url)
    encryptor = load_encryptor(encryption_key)
    store = EvidenceStore(engine, encryptor=encryptor)
    try:
        records = store.all()
    except FieldDecryptionError as exc:
        # `EvidenceStore.all()` decrypts every row before returning any of
        # them (see that method's docstring), so a decrypt failure is
        # caught here, wrapping the whole fetch, rather than inside
        # verify_chain()'s own per-record hash-checking loop -- the
        # failing record's own sequence_number is still named in `str(exc)`
        # (see EvidenceStore._to_model), so the result stays specific and
        # actionable even though `checked_count` cannot reflect partial
        # hash-verification progress that never got to run.
        return ChainVerificationResult(valid=False, checked_count=0, detail=str(exc))
    return verify_chain(records, public_key_hex=public_key_hex)


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
    parser.add_argument(
        "--encryption-key",
        required=False,
        help="FIELD_ENCRYPTION_KEY value (a Fernet key, see "
        '`python -c "from cryptography.fernet import Fernet; '
        'print(Fernet.generate_key().decode())"`), required whenever the deployment '
        "being verified has application-level field encryption enabled. Omit if "
        "encryption was never configured.",
    )
    args = parser.parse_args(argv)

    result = verify_chain_from_database(
        args.database_url, public_key_hex=args.public_key, encryption_key=args.encryption_key
    )
    print(f"checked {result.checked_count} record(s): {result.detail}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
