"""Direct tests for app.core.logging._redact_sensitive — this service handles the
WireGuard config_text/private key it forwards to users, so accidental logging of that
payload is the specific risk this processor guards against."""

from app.core.logging import _REDACT_KEYS, _redact_sensitive


def test_redacts_every_known_sensitive_key():
    event_dict = {key: "super-secret-value" for key in _REDACT_KEYS}
    event_dict["event"] = "config_delivered"

    result = _redact_sensitive(None, "info", dict(event_dict))

    for key in _REDACT_KEYS:
        assert result[key] == "***REDACTED***", f"{key!r} was not redacted"
    assert result["event"] == "config_delivered"


def test_redaction_is_case_insensitive_on_key_name():
    result = _redact_sensitive(None, "info", {"Config_Text": "[Interface]...", "Token": "abc"})
    assert result["Config_Text"] == "***REDACTED***"
    assert result["Token"] == "***REDACTED***"


def test_non_sensitive_keys_pass_through_unchanged():
    event_dict = {"telegram_id": 123456789, "chat_id": 987}
    result = _redact_sensitive(None, "info", dict(event_dict))
    assert result == event_dict
