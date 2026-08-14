"""Direct tests for the subscription-link token primitives in app/core/security.py —
generation entropy, hashing, and the non-secret prefix — plus safe_request_path, the
helper that keeps GET /sub/{token} out of plaintext in request logs. See
app/services/subscription_link_service.py and app/services/subscription_delivery/ for
where these are actually used.
"""

import base64
import hashlib

from app.core.logging import safe_request_path
from app.core.security import (
    generate_subscription_token,
    hash_subscription_token,
    subscription_token_prefix,
)


def test_generated_token_has_256_bits_of_entropy():
    token = generate_subscription_token()
    # secrets.token_urlsafe(32) encodes 32 raw bytes (256 bits) as base64url; the decoded
    # length is the real assertion — the string length varies slightly with padding.
    padded = token + "=" * (-len(token) % 4)
    decoded = base64.urlsafe_b64decode(padded)
    assert len(decoded) == 32


def test_generated_tokens_are_unique():
    tokens = {generate_subscription_token() for _ in range(200)}
    assert len(tokens) == 200


def test_hash_is_deterministic_sha256_hex():
    token = "fixed-token-for-this-test"
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert hash_subscription_token(token) == expected
    assert hash_subscription_token(token) == hash_subscription_token(token)


def test_different_tokens_hash_differently():
    a = generate_subscription_token()
    b = generate_subscription_token()
    assert hash_subscription_token(a) != hash_subscription_token(b)


def test_prefix_is_a_short_non_reversible_slice():
    token = generate_subscription_token()
    prefix = subscription_token_prefix(token)
    assert prefix == token[:8]
    assert len(prefix) < len(token)
    # The prefix alone must not be usable to derive the hash the server actually checks
    # against — spot check that hashing the prefix does not equal hashing the full token.
    assert hash_subscription_token(prefix) != hash_subscription_token(token)


def test_safe_request_path_masks_subscription_links():
    assert safe_request_path("/sub/abc123SECRETtoken") == "/sub/***"
    assert safe_request_path("/sub/") == "/sub/***"


def test_safe_request_path_leaves_other_paths_untouched():
    assert safe_request_path("/api/v1/devices/42") == "/api/v1/devices/42"
    assert safe_request_path("/health") == "/health"
    assert safe_request_path("/subscriptions/me") == "/subscriptions/me"
