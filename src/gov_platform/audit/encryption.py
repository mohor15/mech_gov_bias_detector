"""Application-level field encryption — architecture §13, M11.

Tier two of M11's two-tier encryption-at-rest design (see
`docs/milestones/M11.md` §5.1): opaque, authenticated encryption for a
fixed, named list of columns proven never to participate in any SQL
`WHERE`/`ORDER BY`/`GROUP BY`/uniqueness comparison anywhere in this
codebase — `evidence_chain.payload`, `verdict_reviews.resolution_notes`,
`population_finding_reviews.resolution_notes`, and
`protected_attribute_resolutions.proxy_basis`. Tier one (storage-level
encryption of the Postgres volume itself) is a documented deployment
requirement, not code — see `README.md`.

Every encrypted value is stored as `"gpenc1:" + <Fernet token>`, never a
bare token — a version-prefix marker distinguishing ciphertext from
legacy/unencrypted plaintext at read time, so encryption applies going
forward only, with no backfill migration (§5.1/§8). `is_encrypted`/
`decrypt_field` centralize that marker check in exactly one place: every
read path in this codebase calls `decrypt_field`, never
`FieldEncryptor.decrypt_token` directly, so the "marker detection is
unconditional, before any encryptor is consulted" invariant (§5.1's
minimal-plumbing point 5) cannot drift between call sites.

`FIELD_ENCRYPTION_KEY` must be `Fernet.generate_key()`'s own output (32
url-safe-base64-encoded bytes) — a different encoding than
`SIGNING_PRIVATE_KEY`'s hex convention (§5.1/§12.17). There is
deliberately no ephemeral, auto-generated fallback the way
`audit.signing.load_signer` has for the signing key (§5.1/§12.4): an
encryption key nobody else can reproduce would make already-encrypted
data unrecoverable the moment this process restarts, a failure mode
signing's own fallback does not share.
"""

from __future__ import annotations

from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

_MARKER_PREFIX = "gpenc1:"

#: Substituted for a free-text field (e.g. `resolution_notes`) that cannot
#: be decrypted, per the per-record containment policy §5.1/§12.15
#: establishes for display fields — never used for evidentiary content
#: (`evidence_chain.payload`), which must raise instead of being papered
#: over with a placeholder.
UNREADABLE_PLACEHOLDER = "[unreadable]"


class FieldDecryptionError(Exception):
    """A `"gpenc1:"`-marked value could not be decrypted — wrong or missing
    key, or corrupted ciphertext. Callers must never let this propagate
    silently where doing so would misrepresent what's actually stored —
    see `docs/milestones/M11.md` §5.1/§12.15 for the per-column
    containment policy (evidentiary content raises loudly; free-text
    display fields degrade to `UNREADABLE_PLACEHOLDER`)."""


class FieldEncryptor(Protocol):
    """What every read/write path in this codebase depends on — either
    `FernetFieldEncryptor` (a real key configured) or `NoOpFieldEncryptor`
    (encryption disabled). Every consumer in this codebase is typed
    against this protocol, never against a concrete implementation."""

    def encrypt(self, plaintext: str) -> str:
        """Encrypt `plaintext`, returning a `"gpenc1:"`-marked value ready
        to store. Must be idempotent-safe to call repeatedly (Fernet's own
        non-deterministic IV means the same plaintext never produces the
        same ciphertext twice — by design, see §5.1's own note on why
        `reviewer` cannot be encrypted for exactly this reason)."""
        ...  # pragma: no cover -- a Protocol body, never called directly

    def decrypt_token(self, token: str) -> str:
        """Decrypt a raw Fernet token (the part of a `"gpenc1:"`-marked
        value *after* the marker — callers never pass the marker itself).
        Raises `FieldDecryptionError` if the token cannot be decrypted
        with this encryptor's key. Never called directly by repository/
        store code — always through `decrypt_field`, which owns the
        marker-detection step this method assumes has already happened."""
        ...  # pragma: no cover -- a Protocol body, never called directly


class FernetFieldEncryptor:
    """The real encryptor, wrapping one static Fernet key — architecture
    §5.1. `key` must be `Fernet.generate_key()`'s own output; a hex string
    (e.g. one generated for `SIGNING_PRIVATE_KEY`) raises here, at
    construction time, not silently."""

    def __init__(self, key: str | bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_MARKER_PREFIX}{token}"

    def decrypt_token(self, token: str) -> str:
        try:
            token_bytes = token.encode("ascii")
        except UnicodeEncodeError as exc:
            # A genuine Fernet token is always pure-ASCII base64 -- this
            # path is reached only by the marker-collision case §5.1
            # already names as a real risk (a free-text value that
            # happens to start with "gpenc1:" but was never actually
            # encrypted, e.g. containing non-ASCII characters submitted
            # before encryption was ever enabled). Found during this
            # milestone's own post-implementation hostile review: without
            # this catch, such a value raises an uncaught
            # UnicodeEncodeError here -- never reaching Fernet's own
            # InvalidToken path below -- which would have bypassed every
            # caller's FieldDecryptionError containment entirely (a
            # crashed list response instead of a per-record placeholder).
            raise FieldDecryptionError(
                "cannot decrypt: value is not valid Fernet ciphertext (non-ASCII content)"
            ) from exc
        try:
            return self._fernet.decrypt(token_bytes).decode("utf-8")
        except InvalidToken as exc:
            raise FieldDecryptionError(
                "cannot decrypt: wrong FIELD_ENCRYPTION_KEY or corrupted ciphertext"
            ) from exc


class NoOpFieldEncryptor:
    """The default collaborator when `FIELD_ENCRYPTION_KEY` is unset —
    encryption is simply off (§5.1). `encrypt` returns its input
    completely unchanged, never `"gpenc1:"`-marked, so newly-written rows
    stay plaintext exactly as every milestone before M11 already stored
    them. `decrypt_token` always raises: this collaborator holds no key,
    so a marked value reaching it (a row encrypted by a
    differently-configured process, or written before this process's own
    key was removed — see §5.1's disclosed plaintext-regression risk) can
    never be read, and must fail the same specific, catchable way an
    actually-wrong key would. "No-op" describes *no decryption
    capability*, not *no awareness of ciphertext* (§5.1/§12.5's
    minimal-plumbing point 5) — it must never silently hand raw ciphertext
    back to a caller that will then try to parse it as plaintext."""

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt_token(self, token: str) -> str:
        raise FieldDecryptionError(
            "cannot decrypt gpenc1-marked value: no FIELD_ENCRYPTION_KEY is configured"
        )


def is_encrypted(value: str) -> bool:
    """Whether `value` carries the `"gpenc1:"` marker — the sole,
    unconditional signal every read path uses to distinguish ciphertext
    from legacy/unencrypted plaintext, checked before any encryptor is
    consulted."""
    return value.startswith(_MARKER_PREFIX)


def decrypt_field(value: str, encryptor: FieldEncryptor) -> str:
    """The one function every read path in this codebase calls to recover
    a possibly-encrypted column's plaintext — never
    `encryptor.decrypt_token` directly. A value with no `"gpenc1:"` marker
    is legacy/unencrypted plaintext, returned unchanged without ever
    reaching `encryptor`; a marked value is always handed to
    `encryptor.decrypt_token`, including when `encryptor` is
    `NoOpFieldEncryptor` (which then raises `FieldDecryptionError`, never
    silently returns the raw ciphertext) — see this module's docstring
    and `docs/milestones/M11.md` §5.1's minimal-plumbing point 5."""
    if not is_encrypted(value):
        return value
    return encryptor.decrypt_token(value[len(_MARKER_PREFIX) :])


def load_encryptor(field_encryption_key: str | None) -> FieldEncryptor:
    """Builds the real encryptor from `Settings.FIELD_ENCRYPTION_KEY`, or
    `NoOpFieldEncryptor` if unset — deliberately no ephemeral,
    auto-generated fallback, unlike `audit.signing.load_signer` (§5.1/
    §12.4)."""
    if field_encryption_key is None:
        return NoOpFieldEncryptor()
    return FernetFieldEncryptor(field_encryption_key)
