"""Pure hash-chain primitives — extracted from `evidence_store.py` in M1,
per the frozen plan's explicit file list. Unchanged algorithm from M0: each
record's hash covers its own canonical payload plus the previous record's
hash. Pure functions, no DB dependency — used by both `EvidenceStore`
(writing the chain) and `verify_chain` (independently re-validating it), and
fully unit-testable without Postgres.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS_HASH = "0" * 64


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic serialization so the same content always hashes the same way."""
    return json.dumps(payload, sort_keys=True, default=str)


def compute_hash(previous_hash: str, payload_json: str) -> str:
    digest = hashlib.sha256(f"{previous_hash}:{payload_json}".encode())
    return digest.hexdigest()
