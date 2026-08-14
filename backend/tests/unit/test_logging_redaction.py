"""Direct tests for app.core.logging._redact_sensitive — the structlog processor that's
the last line of defense against a WireGuard private key, password, or webhook secret
ending up in a log line by mistake (see docs/wireguard.md's "Private key handling"
section, which calls this out explicitly as defense in depth, not the primary control).
"""

from app.core.logging import _REDACT_KEYS, _redact_sensitive


def test_redacts_every_known_sensitive_key():
    event_dict = {key: "super-secret-value" for key in _REDACT_KEYS}
    event_dict["event"] = "something_happened"

    result = _redact_sensitive(None, "info", dict(event_dict))

    for key in _REDACT_KEYS:
        assert result[key] == "***REDACTED***", f"{key!r} was not redacted"
    assert result["event"] == "something_happened"


def test_redaction_is_case_insensitive_on_key_name():
    result = _redact_sensitive(
        None, "info", {"Private_Key": "abc", "PASSWORD": "def", "Authorization": "Bearer xyz"}
    )
    assert result["Private_Key"] == "***REDACTED***"
    assert result["PASSWORD"] == "***REDACTED***"
    assert result["Authorization"] == "***REDACTED***"


def test_non_sensitive_keys_pass_through_unchanged():
    event_dict = {"user_id": 42, "path": "/api/v1/devices", "status_code": 201}
    result = _redact_sensitive(None, "info", dict(event_dict))
    assert result == event_dict


def test_redaction_only_matches_key_names_not_value_contents():
    """A documented boundary, not a bug: redaction is key-based (safe, no false
    positives/negatives from guessing at free text), so a secret embedded in an unrelated
    field's *value* — e.g. inside an exception message — is not caught by this processor.
    Structured logging call sites are expected to never put a secret in a non-sensitively-
    named field in the first place; this test exists so that expectation isn't silently
    relaxed later by someone assuming the redactor scans values too."""
    result = _redact_sensitive(None, "info", {"message": "login failed for token abc123"})
    assert result["message"] == "login failed for token abc123"
