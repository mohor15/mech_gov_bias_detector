"""Signing and standalone verification for Population Findings —
architecture §13, M6.

Population findings are signed the same way evidence records are
(`audit/signing.py`, reused unchanged — it's already a pure function with
no `evidence_chain`-specific dependency), but they are **not chained**
(`docs/milestones/M6.md` §13.5): there is no `previous_hash` to fold in,
because a population finding isn't a link in a sequence the way an
evidence record is — see `db/repositories/population_finding.py`'s
docstring. `population_finding_hash` is therefore a plain content hash
over the finding's own canonical payload, not `hash_chain.compute_hash`'s
chained variant.

The hashed/signed payload includes `classification_snapshot` — the
hostile-review-pass fix for `docs/milestones/M6.md` §13.16: without it, a
valid signature would only prove the bytes weren't altered, not that
"verify this finding" is a well-defined question, since two different
`protected_attribute_rules` states could otherwise produce
identically-shaped, identically-signed-looking records for different
reasons. See `schemas/population_finding.py`'s docstring.

Mirrors `audit/verify_chain.py`'s shape: a pure core (`verify_population_findings`,
no database dependency, fully unit-testable with hand-built records
including deliberately corrupted ones) plus a thin, Postgres-dependent CLI
wrapper. Signing without any verifier would be exactly the "infrastructure
with zero callers" pattern this milestone's own design review argued
against for its read API (`docs/milestones/M6.md` §13.6/§13.12) — this
module is that verifier, shipped alongside signing, not deferred.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence

from pydantic import BaseModel

from gov_platform.audit.hash_chain import canonical_json
from gov_platform.audit.signing import verify_signature
from gov_platform.db.repositories.population_finding import (
    PopulationFindingRecord,
    PopulationFindingRepository,
)
from gov_platform.db.session import create_db_engine
from gov_platform.schemas.population_finding import PopulationFinding


class PopulationFindingVerificationResult(BaseModel):
    valid: bool
    checked_count: int
    first_invalid_id: str | None = None
    detail: str


def population_finding_hash(finding: PopulationFinding) -> str:
    """A plain content hash over `finding`'s own canonical payload --
    deliberately not `hash_chain.compute_hash` (no chain, no previous
    record to fold in; see this module's docstring)."""
    return hashlib.sha256(canonical_json(finding.model_dump(mode="json")).encode()).hexdigest()


def verify_population_findings(
    records: Sequence[PopulationFindingRecord], *, public_key_hex: str
) -> PopulationFindingVerificationResult:
    """Re-derive each record's content hash and check its signature
    against `public_key_hex`. Records with no signature (there should be
    none — population findings have existed only since M6, signed from
    the start — but a manually-inserted or future unsigned row is treated
    the same way `verify_chain` treats pre-M5 evidence rows: skipped, not
    failed)."""
    for index, record in enumerate(records):
        if record.signature is None:
            continue

        expected_hash = population_finding_hash(record.as_population_finding())
        if not verify_signature(expected_hash, record.signature, public_key_hex):
            return PopulationFindingVerificationResult(
                valid=False,
                checked_count=index,
                first_invalid_id=record.id,
                detail=(
                    f"population finding {record.id}: signature does not verify against "
                    "the provided public key"
                ),
            )

    return PopulationFindingVerificationResult(
        valid=True, checked_count=len(records), detail="all signatures valid"
    )


def verify_population_findings_from_database(
    database_url: str, *, public_key_hex: str
) -> PopulationFindingVerificationResult:
    from sqlalchemy.orm import Session

    engine = create_db_engine(database_url)
    with Session(engine) as session:
        records = PopulationFindingRepository().list_all(session)
    return verify_population_findings(records, public_key_hex=public_key_hex)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every population finding's signature end to end."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--public-key",
        required=True,
        help="Hex-encoded Ed25519 public key to verify signatures against (see "
        "`python -m gov_platform.audit.signing --private-key ...`).",
    )
    args = parser.parse_args(argv)

    result = verify_population_findings_from_database(
        args.database_url, public_key_hex=args.public_key
    )
    print(f"checked {result.checked_count} population finding(s): {result.detail}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
