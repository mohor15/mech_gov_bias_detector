"""Application-level field encryption — pure, no DB. See
`audit/encryption.py`'s module docstring for the guarantee this adds on
top of storage-level encryption.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from gov_platform.audit.encryption import (
    UNREADABLE_PLACEHOLDER,
    FernetFieldEncryptor,
    FieldDecryptionError,
    NoOpFieldEncryptor,
    decrypt_field,
    is_encrypted,
    load_encryptor,
)


def _fresh_key() -> str:
    return Fernet.generate_key().decode("ascii")


# --- FernetFieldEncryptor --------------------------------------------------


def test_encrypt_then_decrypt_round_trips() -> None:
    encryptor = FernetFieldEncryptor(_fresh_key())

    ciphertext = encryptor.encrypt("some sensitive text")

    assert ciphertext != "some sensitive text"
    assert is_encrypted(ciphertext)
    assert decrypt_field(ciphertext, encryptor) == "some sensitive text"


def test_encrypt_marks_the_value_with_the_gpenc1_prefix() -> None:
    encryptor = FernetFieldEncryptor(_fresh_key())

    ciphertext = encryptor.encrypt("hello")

    assert ciphertext.startswith("gpenc1:")


def test_encrypting_the_same_plaintext_twice_produces_different_ciphertext() -> None:
    # Fernet's own non-deterministic IV -- the exact property that makes
    # encrypting reviewer (an equality-compared column) unsafe, see
    # docs/milestones/M11.md §4.1/§5.1.
    encryptor = FernetFieldEncryptor(_fresh_key())

    first = encryptor.encrypt("same plaintext")
    second = encryptor.encrypt("same plaintext")

    assert first != second
    assert decrypt_field(first, encryptor) == decrypt_field(second, encryptor) == "same plaintext"


def test_decrypting_with_the_wrong_key_raises_field_decryption_error() -> None:
    encryptor_a = FernetFieldEncryptor(_fresh_key())
    encryptor_b = FernetFieldEncryptor(_fresh_key())
    ciphertext = encryptor_a.encrypt("secret")

    with pytest.raises(FieldDecryptionError):
        decrypt_field(ciphertext, encryptor_b)


def test_decrypting_corrupted_ciphertext_raises_field_decryption_error() -> None:
    encryptor = FernetFieldEncryptor(_fresh_key())
    ciphertext = encryptor.encrypt("secret")
    corrupted = ciphertext[:-4] + "abcd"

    with pytest.raises(FieldDecryptionError):
        decrypt_field(corrupted, encryptor)


def test_a_non_ascii_marker_collision_value_raises_field_decryption_error_not_a_crash() -> None:
    # Found during this milestone's own post-implementation hostile review:
    # a free-text value submitted before encryption was ever enabled that
    # happens to start with "gpenc1:" (the exact marker-collision risk
    # docs/milestones/M11.md §5.1 already names) and contains non-ASCII
    # characters must still degrade to FieldDecryptionError, not an
    # uncaught UnicodeEncodeError bypassing every caller's containment.
    encryptor = FernetFieldEncryptor(_fresh_key())
    poisoned = "gpenc1:héllo wörld, this was never really ciphertext"

    with pytest.raises(FieldDecryptionError):
        decrypt_field(poisoned, encryptor)


def test_a_hex_string_key_is_rejected_at_construction_not_silently() -> None:
    # SIGNING_PRIVATE_KEY's own convention -- deliberately the wrong shape
    # for a Fernet key, see docs/milestones/M11.md §5.1/§12.17.
    hex_key = "a" * 64
    with pytest.raises(Exception):  # noqa: B017 -- cryptography raises its own ValueError subclass
        FernetFieldEncryptor(hex_key)


# --- NoOpFieldEncryptor -----------------------------------------------------


def test_no_op_encryptor_returns_plaintext_unchanged_and_unmarked() -> None:
    encryptor = NoOpFieldEncryptor()

    result = encryptor.encrypt("plaintext value")

    assert result == "plaintext value"
    assert not is_encrypted(result)


def test_decrypt_field_returns_unmarked_values_unchanged_even_with_no_op_encryptor() -> None:
    encryptor = NoOpFieldEncryptor()

    assert decrypt_field("legacy plaintext row", encryptor) == "legacy plaintext row"


def test_no_op_encryptor_raises_on_a_marked_value_it_cannot_read() -> None:
    # The exact regression this document's third hostile-review pass named:
    # a literal pass-through would silently hand raw ciphertext to a caller
    # expecting plaintext (docs/milestones/M11.md §5.1 minimal-plumbing
    # point 5). "No-op" must mean no decryption *capability*, not no
    # awareness of ciphertext.
    real_encryptor = FernetFieldEncryptor(_fresh_key())
    marked_value = real_encryptor.encrypt("secret")
    no_op = NoOpFieldEncryptor()

    with pytest.raises(FieldDecryptionError):
        decrypt_field(marked_value, no_op)


# --- decrypt_field / is_encrypted marker semantics --------------------------


def test_is_encrypted_is_false_for_plain_strings() -> None:
    assert is_encrypted("just some text") is False
    assert is_encrypted("") is False


def test_is_encrypted_is_true_only_for_the_exact_marker_prefix() -> None:
    assert is_encrypted("gpenc1:abc") is True
    assert is_encrypted("gpenc1") is False
    assert is_encrypted(" gpenc1:abc") is False


def test_decrypt_field_never_calls_the_encryptor_for_unmarked_plaintext() -> None:
    class _ExplodingEncryptor:
        def encrypt(self, plaintext: str) -> str:
            raise AssertionError("must not be called")

        def decrypt_token(self, token: str) -> str:
            raise AssertionError("must not be called for unmarked input")

    assert decrypt_field("plain value, never marked", _ExplodingEncryptor()) == (
        "plain value, never marked"
    )


# --- load_encryptor ----------------------------------------------------------


def test_load_encryptor_with_no_key_returns_a_no_op_encryptor() -> None:
    encryptor = load_encryptor(None)

    assert isinstance(encryptor, NoOpFieldEncryptor)


def test_load_encryptor_with_a_key_returns_a_real_fernet_encryptor() -> None:
    encryptor = load_encryptor(_fresh_key())

    assert isinstance(encryptor, FernetFieldEncryptor)


def test_load_encryptor_never_generates_an_ephemeral_key() -> None:
    # Deliberately asymmetric with audit.signing.load_signer -- there is no
    # "no key configured, generate one" fallback for encryption at all, see
    # docs/milestones/M11.md §5.1/§12.4.
    encryptor_a = load_encryptor(None)
    encryptor_b = load_encryptor(None)

    assert isinstance(encryptor_a, NoOpFieldEncryptor)
    assert isinstance(encryptor_b, NoOpFieldEncryptor)
    # Both are stateless no-ops -- unlike two ephemeral signing keys, there
    # is no "different key per instance" to even compare.
    assert encryptor_a.encrypt("x") == encryptor_b.encrypt("x") == "x"


def test_unreadable_placeholder_is_a_stable_constant() -> None:
    assert UNREADABLE_PLACEHOLDER == "[unreadable]"
