"""Direct tests for app.core.logging._redact_sensitive — the vpn-agent generates X25519
private keys on every /peers call (see app/wireguard/keygen.py) and verifies HMAC
signatures on every inbound request; this processor is what stops either from ending up
in a log line by mistake."""

from app.core.logging import _REDACT_KEYS, _redact_sensitive


def test_redacts_every_known_sensitive_key():
    event_dict = {key: "super-secret-value" for key in _REDACT_KEYS}
    event_dict["event"] = "peer_created"

    result = _redact_sensitive(None, "info", dict(event_dict))

    for key in _REDACT_KEYS:
        assert result[key] == "***REDACTED***", f"{key!r} was not redacted"
    assert result["event"] == "peer_created"


def test_redaction_is_case_insensitive_on_key_name():
    result = _redact_sensitive(None, "info", {"Private_Key": "abc", "Signature": "xyz"})
    assert result["Private_Key"] == "***REDACTED***"
    assert result["Signature"] == "***REDACTED***"


def test_non_sensitive_keys_pass_through_unchanged():
    event_dict = {"device_id": 1, "assigned_ip": "10.66.0.2/32"}
    result = _redact_sensitive(None, "info", dict(event_dict))
    assert result == event_dict
