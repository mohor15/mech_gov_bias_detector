"""Ed25519 evidence signing — pure, no DB. See `audit/signing.py`'s
module docstring for the guarantee this adds on top of the hash chain.
"""

from __future__ import annotations

import pytest

from gov_platform.audit.signing import (
    generate_private_key_hex,
    load_signer,
    main,
    verify_signature,
)


def test_a_signature_verifies_against_its_own_public_key() -> None:
    signer = load_signer(None)

    signature = signer.sign("some-record-hash")

    assert signer.verify("some-record-hash", signature) is True
    assert verify_signature("some-record-hash", signature, signer.public_key_hex()) is True


def test_a_tampered_record_hash_fails_verification() -> None:
    signer = load_signer(None)
    signature = signer.sign("original-hash")

    assert signer.verify("tampered-hash", signature) is False


def test_a_signature_from_a_different_key_fails_verification() -> None:
    signer_a = load_signer(None)
    signer_b = load_signer(None)
    signature = signer_a.sign("some-record-hash")

    assert signer_b.verify("some-record-hash", signature) is False


def test_load_signer_with_no_key_generates_a_fresh_ephemeral_key_each_time() -> None:
    signer_a = load_signer(None)
    signer_b = load_signer(None)

    assert signer_a.public_key_hex() != signer_b.public_key_hex()


def test_load_signer_with_an_explicit_key_is_deterministic() -> None:
    private_key_hex = generate_private_key_hex()

    signer_a = load_signer(private_key_hex)
    signer_b = load_signer(private_key_hex)

    assert signer_a.public_key_hex() == signer_b.public_key_hex()
    # Proves cross-instance/cross-process verification actually works when
    # a real key is configured, unlike the ephemeral default.
    signature = signer_a.sign("some-record-hash")
    assert signer_b.verify("some-record-hash", signature) is True


def test_key_id_defaults_to_default_and_is_configurable() -> None:
    assert load_signer(None).key_id == "default"
    assert load_signer(None, key_id="custom").key_id == "custom"


def test_generate_private_key_hex_produces_a_valid_32_byte_seed() -> None:
    private_key_hex = generate_private_key_hex()

    assert len(bytes.fromhex(private_key_hex)) == 32
    # Must actually be usable to construct a signer.
    load_signer(private_key_hex)


def test_main_prints_the_derived_public_key(capsys: pytest.CaptureFixture[str]) -> None:
    private_key_hex = generate_private_key_hex()
    expected_public_key_hex = load_signer(private_key_hex).public_key_hex()

    exit_code = main(["--private-key", private_key_hex])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == expected_public_key_hex
