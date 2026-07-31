"""Pure, DB-agnostic bearer-token primitives — architecture (no numbered
section; see `docs/milestones/M13.md` Sourcing note), M13.

The identical "pure, no DB, no framework import, unit-testable with no
Postgres" shape `audit/hash_chain.py` (M0/M1) already established for
this platform's other pure cryptographic primitives. No new dependency:
stdlib `secrets`/`hashlib`/`hmac` only — not even a reuse of the
`cryptography` package (already present since M5), which this specific
job doesn't need (`docs/milestones/M13.md` TL;DR, Revision note item 13).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# 256 bits of entropy -- matches SIGNING_PRIVATE_KEY's own seed length
# (audit/signing.py).
_TOKEN_BYTES = 32


def generate_token() -> str:
    """A fresh, cryptographically-random bearer token. Never persisted in
    plaintext anywhere -- see `hash_token`."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """One-way digest stored in `principals.token_hash`. SHA-256, not a
    slow/adaptive password hash (bcrypt/argon2/scrypt) -- deliberately:
    `token` is a 256-bit random value with no human-memorable structure to
    defend against offline brute-forcing, the same property that makes a
    fast digest correct for GitHub/Stripe/AWS-style API keys. See
    `docs/milestones/M13.md` Revision note, item 3.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    """Constant-time comparison -- a naive `==` here would leak timing
    information about how many leading hex characters of a guessed hash
    matched, the same class of defect `hmac.compare_digest` exists to
    close."""
    return hmac.compare_digest(hash_token(token), token_hash)
