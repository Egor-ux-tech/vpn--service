import pytest
from pydantic import ValidationError

from app.core.config import BotSettings


def test_production_with_default_secrets_is_rejected():
    # conftest.py sets INTERNAL_SERVICE_TOKEN in the process environment for the rest of
    # this suite — pass the insecure values explicitly so this test isn't at their mercy.
    with pytest.raises(ValidationError, match="insecure placeholder"):
        BotSettings(
            environment="production",
            telegram_bot_token="123:abc",
            telegram_webhook_secret="change-me",
            internal_service_token="change-me-shared-secret-for-service-to-service-calls",
        )


def test_production_with_real_secrets_is_accepted():
    settings = BotSettings(
        environment="production",
        telegram_bot_token="123:abc",
        telegram_webhook_secret="a-real-random-webhook-secret",
        internal_service_token="a-real-random-internal-token",
    )
    assert settings.environment == "production"


def test_development_allows_default_secrets():
    settings = BotSettings(
        environment="development",
        internal_service_token="change-me-shared-secret-for-service-to-service-calls",
    )
    assert settings.internal_service_token == "change-me-shared-secret-for-service-to-service-calls"
