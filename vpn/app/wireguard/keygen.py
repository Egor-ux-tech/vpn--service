"""Generates WireGuard-compatible X25519 keypairs without shelling out to `wg genkey`.

WireGuard uses Curve25519 for its key exchange, so a keypair generated with the standard
`cryptography` library's X25519 implementation and base64-encoded is byte-for-byte
equivalent to what `wg genkey`/`wg pubkey` would produce. This keeps key generation
testable and independent of whether the `wireguard-tools` CLI is installed.
"""

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


@dataclass(frozen=True, slots=True)
class WireGuardKeypair:
    private_key: str
    public_key: str


def generate_keypair() -> WireGuardKeypair:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    return WireGuardKeypair(
        private_key=base64.b64encode(private_bytes).decode("ascii"),
        public_key=base64.b64encode(public_bytes).decode("ascii"),
    )


def public_key_from_private(private_key_b64: str) -> str:
    private_bytes = base64.b64decode(private_key_b64)
    private_key = X25519PrivateKey.from_private_bytes(private_bytes)
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(public_bytes).decode("ascii")
