import base64

from app.wireguard.keygen import generate_keypair, public_key_from_private


def test_generate_keypair_produces_valid_base64_32_byte_keys():
    keypair = generate_keypair()
    assert len(base64.b64decode(keypair.private_key)) == 32
    assert len(base64.b64decode(keypair.public_key)) == 32


def test_generate_keypair_is_unique_each_call():
    a = generate_keypair()
    b = generate_keypair()
    assert a.private_key != b.private_key
    assert a.public_key != b.public_key


def test_public_key_from_private_is_deterministic():
    keypair = generate_keypair()
    assert public_key_from_private(keypair.private_key) == keypair.public_key
