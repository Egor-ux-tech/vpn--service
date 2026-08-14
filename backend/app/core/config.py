from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values these settings ship with in .env.example — safe for local dev, never for
# production. Checked at startup (see _reject_default_secrets_in_production) rather than
# merely documented, so a forgotten override fails loudly instead of shipping quietly.
_INSECURE_DEFAULTS = {
    "jwt_secret": "change-me-to-a-long-random-string",
    "admin_secret": "change-me-admin-bootstrap-secret",
    "internal_service_token": "change-me-shared-secret-for-service-to-service-calls",
    "telegram_webhook_secret": "change-me",
    "payment_webhook_secret": "change-me",
    "vpn_agent_shared_secret": "change-me-vpn-agent-secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    backend_cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://vpnservice:change-me@localhost:5432/vpnservice"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(default="change-me-to-a-long-random-string")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    admin_secret: str = "change-me-admin-bootstrap-secret"
    internal_service_token: str = "change-me-shared-secret-for-service-to-service-calls"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "change-me"
    bot_notify_base_url: str = "http://bot:8801"

    payment_provider: str = "mock"
    payment_provider_key: str = ""
    payment_provider_shop_id: str = ""
    payment_webhook_secret: str = "change-me"

    vpn_default_network: str = "10.66.0.0/16"
    vpn_dns: str = "1.1.1.1,1.0.0.1"
    vpn_agent_shared_secret: str = "change-me-vpn-agent-secret"
    vpn_agent_port: int = 8800

    rate_limit_default: str = "100/minute"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def vpn_dns_list(self) -> list[str]:
        return [ip.strip() for ip in self.vpn_dns.split(",") if ip.strip()]

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> "Settings":
        if not self.is_production:
            return self
        leftover = [
            field
            for field, insecure_value in _INSECURE_DEFAULTS.items()
            if getattr(self, field) == insecure_value
        ]
        if leftover:
            raise ValueError(
                "ENVIRONMENT=production but these settings still have their insecure "
                f"placeholder values from .env.example: {', '.join(sorted(leftover))}. "
                "Set real secrets before starting in production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
