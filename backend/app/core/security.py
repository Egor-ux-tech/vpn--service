import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import jwt
from jwt import PyJWTError

from app.core.config import get_settings

# bcrypt's algorithm caps input at 72 bytes; passwords are truncated the same way bcrypt
# itself always has, rather than depending on passlib (unmaintained, breaks on bcrypt>=4.1).
_BCRYPT_MAX_BYTES = 72


class TokenType(StrEnum):
    """Tags the JWT's "type" claim so a token can't be replayed for a purpose it wasn't
    issued for — checked explicitly in `get_current_admin`. ACCESS is the only kind of
    token this service issues; there is no refresh-token mechanism (see AdminAuthService)."""

    ACCESS = "access"


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(truncated, hashed_password.encode("ascii"))
    except ValueError:
        return False


def create_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": TokenType.ACCESS.value,
        "iat": now,
        "exp": expire,
        "jti": secrets.token_hex(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except PyJWTError:
        return None


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sign_hmac(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_hmac(payload: bytes, secret: str, signature: str) -> bool:
    expected = sign_hmac(payload, secret)
    return constant_time_compare(expected, signature)


def generate_internal_id(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(16)}"
