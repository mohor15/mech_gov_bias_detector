"""Pure bearer-token primitives — no DB involved, runs anywhere.

Mirrors `tests/unit/audit/test_hash_chain.py`'s own "pure primitive,
DB-independent-first" discipline for this milestone's own new pure
module — see `docs/milestones/M13.md` §5.7.
"""

from __future__ import annotations

from gov_platform.access.tokens import generate_token, hash_token, token_matches


def test_generate_token_produces_a_non_trivial_random_value() -> None:
    token = generate_token()
    assert isinstance(token, str)
    assert len(token) > 32


def test_generate_token_is_not_deterministic() -> None:
    assert generate_token() != generate_token()


def test_hash_token_is_deterministic() -> None:
    token = generate_token()
    assert hash_token(token) == hash_token(token)


def test_hash_token_produces_64_hex_chars() -> None:
    digest = hash_token(generate_token())
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_token_never_reproduces_the_plaintext() -> None:
    token = generate_token()
    assert hash_token(token) != token


def test_different_tokens_hash_differently() -> None:
    assert hash_token(generate_token()) != hash_token(generate_token())


def test_token_matches_is_true_for_the_originating_token() -> None:
    token = generate_token()
    assert token_matches(token, hash_token(token)) is True


def test_token_matches_is_false_for_a_different_token() -> None:
    token = generate_token()
    other = generate_token()
    assert token_matches(other, hash_token(token)) is False


def test_token_matches_is_false_for_a_garbled_hash() -> None:
    token = generate_token()
    assert token_matches(token, "not-a-real-hash") is False
