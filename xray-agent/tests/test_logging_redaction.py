"""Direct tests for app.core.logging._redact_sensitive — every VLESS UUID this agent
handles is a bearer credential (see app/xray/reconciler.py's module docstring), and this
processor is what stops one from ending up in a log line by mistake."""

from app.core.logging import _REDACT_KEYS, _redact_sensitive


def test_redacts_every_known_sensitive_key():
    event_dict = {key: "super-secret-value" for key in _REDACT_KEYS}
    event_dict["event"] = "vless_user_created"

    result = _redact_sensitive(None, "info", dict(event_dict))

    for key in _REDACT_KEYS:
        assert result[key] == "***REDACTED***", f"{key!r} was not redacted"
    assert result["event"] == "vless_user_created"


def test_redaction_is_case_insensitive_on_key_name():
    result = _redact_sensitive(None, "info", {"UUID": "abc", "Signature": "xyz"})
    assert result["UUID"] == "***REDACTED***"
    assert result["Signature"] == "***REDACTED***"


def test_non_sensitive_keys_pass_through_unchanged():
    event_dict = {"device_id": 1, "inbound_tag": "vless-reality-in"}
    result = _redact_sensitive(None, "info", dict(event_dict))
    assert result == event_dict


def test_vless_uuid_and_reality_key_and_shared_secret_are_in_the_redact_list():
    assert "vless_uuid" in _REDACT_KEYS
    assert "uuid" in _REDACT_KEYS
    assert "reality_private_key" in _REDACT_KEYS
    assert "xray_agent_shared_secret" in _REDACT_KEYS
