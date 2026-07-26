"""Pure hash-chain primitives — no DB involved, runs anywhere.

Supersedes the hash-related assertions from M0's `test_evidence_store.py`
now that `hash_chain.py` is its own module (per the frozen M1 file list);
the algorithm itself is byte-for-byte unchanged from M0.
"""

from __future__ import annotations

from gov_platform.audit.hash_chain import GENESIS_HASH, canonical_json, compute_hash


def test_genesis_hash_is_64_zero_chars() -> None:
    assert GENESIS_HASH == "0" * 64
    assert len(GENESIS_HASH) == 64


def test_canonical_json_is_deterministic_regardless_of_key_order() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_compute_hash_is_deterministic() -> None:
    payload = canonical_json({"event": "evt-001"})
    assert compute_hash(GENESIS_HASH, payload) == compute_hash(GENESIS_HASH, payload)


def test_compute_hash_changes_with_previous_hash() -> None:
    payload = canonical_json({"event": "evt-001"})
    first = compute_hash(GENESIS_HASH, payload)
    second = compute_hash(first, payload)
    assert first != second


def test_compute_hash_changes_with_payload() -> None:
    a = compute_hash(GENESIS_HASH, canonical_json({"event": "evt-001"}))
    b = compute_hash(GENESIS_HASH, canonical_json({"event": "evt-002"}))
    assert a != b


def test_compute_hash_produces_64_hex_chars() -> None:
    digest = compute_hash(GENESIS_HASH, canonical_json({"event": "evt-001"}))
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
