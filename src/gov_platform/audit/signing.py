"""Ed25519 evidence signing — architecture §13, M5.

The hash chain (M1) proves internal consistency — that a record hasn't
been altered after being chained. It proves nothing about *who* produced a
given record. Signing adds authenticity: a third party holding the public
key can verify a record was produced by this specific deployment's signing
key, a genuinely different guarantee.

Ed25519, a single static keypair, no KMS/HSM, no rotation — real key
custody is real infrastructure scope this platform has no second
deployment environment to design correctly against yet. See
`docs/milestones/M5.md` §13.8. `signing_key_id` (not the raw key) travels
with every signed record so a future key-rotation milestone can tell which
key verifies which historical record without guessing.

Pure, no DB dependency — mirrors `hash_chain.py`'s shape. `EvidenceStore`
signs at write time; `verify_chain` (given the public key) verifies
independently at read time.
"""

from __future__ import annotations

import argparse
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_KEY_ID = "default"


class EvidenceSigner:
    """Wraps one Ed25519 keypair, loaded once at construction."""

    def __init__(self, private_key: Ed25519PrivateKey, *, key_id: str = DEFAULT_KEY_ID) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self.key_id = key_id

    def sign(self, record_hash: str) -> str:
        return self._private_key.sign(record_hash.encode()).hex()

    def verify(self, record_hash: str, signature_hex: str) -> bool:
        return verify_signature(record_hash, signature_hex, self.public_key_hex())

    def public_key_hex(self) -> str:
        return self._public_key.public_bytes_raw().hex()


def verify_signature(record_hash: str, signature_hex: str, public_key_hex: str) -> bool:
    """Standalone verification against a public key alone — what a party
    with no access to the private key (e.g. `verify_chain`'s CLI, a third
    party) actually has."""
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    try:
        public_key.verify(bytes.fromhex(signature_hex), record_hash.encode())
    except InvalidSignature:
        return False
    return True


def generate_private_key_hex() -> str:
    """Provisions a new signing key, e.g. for `GOV_PLATFORM_SIGNING_PRIVATE_KEY`.
    Not called by the app itself — an operator/ops-tooling utility."""
    return Ed25519PrivateKey.generate().private_bytes_raw().hex()


def load_signer(private_key_hex: str | None, *, key_id: str = DEFAULT_KEY_ID) -> EvidenceSigner:
    """Builds a signer from a hex-encoded 32-byte Ed25519 seed, or a fresh,
    process-local ephemeral key if `private_key_hex` is `None` — see
    `config/settings.py`'s `SIGNING_PRIVATE_KEY` docstring for what that
    fallback does and doesn't guarantee."""
    private_key = (
        Ed25519PrivateKey.generate()
        if private_key_hex is None
        else Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    )
    return EvidenceSigner(private_key, key_id=key_id)


def main(argv: list[str] | None = None) -> int:
    """Ops utility: derive the public key hex for a given private key, to
    hand to `verify_chain --public-key`. Not used by the running app."""
    parser = argparse.ArgumentParser(
        description="Derive an Ed25519 public key hex from a private key hex."
    )
    parser.add_argument("--private-key", required=True, help="Hex-encoded 32-byte private key")
    args = parser.parse_args(argv)

    signer = load_signer(args.private_key)
    print(signer.public_key_hex())
    return 0


if __name__ == "__main__":
    sys.exit(main())
