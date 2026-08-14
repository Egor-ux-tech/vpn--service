import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_with_default_secrets_is_rejected():
    with pytest.raises(ValidationError, match="insecure placeholder values"):
        Settings(environment="production", database_url="postgresql+asyncpg://x/y")


def test_production_with_real_secrets_is_accepted():
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://x/y",
        jwt_secret="a-genuinely-random-64-char-secret-not-from-the-example-file",
        admin_secret="another-genuinely-random-secret",
        internal_service_token="yet-another-random-secret",
        telegram_webhook_secret="random-webhook-secret",
        payment_webhook_secret="random-payment-webhook-secret",
        vpn_agent_shared_secret="random-agent-secret",
        xray_agent_shared_secret="random-xray-agent-secret",
    )
    assert settings.environment == "production"


def test_development_allows_default_secrets():
    settings = Settings(environment="development")
    assert settings.is_production is False
