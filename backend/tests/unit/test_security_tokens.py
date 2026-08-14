"""The service used to issue a refresh token alongside every access token (see
docs/PRODUCTION_READINESS.md) with no endpoint anywhere that ever consumed, rotated, or
revoked it, and no frontend that even read it out of the login response — a dead,
unrevocable 30-day-lived credential. It was removed rather than completed, since nothing
in the product actually needs silent token renewal today. These tests lock in the
resulting single-token design: create_token always mints an ACCESS token, and
get_current_admin's "type" claim check still rejects anything else.
"""

from app.core.config import get_settings
from app.core.security import TokenType, create_token, decode_token


def test_create_token_issues_an_access_token() -> None:
    token = create_token("42")
    payload = decode_token(token)
    assert payload is not None
    assert payload["type"] == TokenType.ACCESS.value
    assert payload["sub"] == "42"


def test_create_token_expiry_matches_access_token_setting() -> None:
    settings = get_settings()
    token = create_token("1")
    payload = decode_token(token)
    assert payload is not None
    expected_lifetime_seconds = settings.jwt_access_token_expire_minutes * 60
    actual_lifetime_seconds = payload["exp"] - payload["iat"]
    assert actual_lifetime_seconds == expected_lifetime_seconds


def test_token_type_has_no_refresh_variant() -> None:
    """Guards against the refresh mechanism quietly creeping back in piecemeal."""
    assert {member.value for member in TokenType} == {"access"}


def test_create_token_carries_extra_claims() -> None:
    token = create_token("7", {"role": "superadmin", "kind": "admin"})
    payload = decode_token(token)
    assert payload is not None
    assert payload["role"] == "superadmin"
    assert payload["kind"] == "admin"
