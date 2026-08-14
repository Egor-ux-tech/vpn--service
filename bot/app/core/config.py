from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {
    "telegram_webhook_secret": "change-me",
    "internal_service_token": "change-me-shared-secret-for-service-to-service-calls",
}


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "change-me"
    telegram_admin_ids: list[int] = []

    backend_api_base_url: str = "http://localhost:8000"
    internal_service_token: str = "change-me-shared-secret-for-service-to-service-calls"

    request_timeout_seconds: float = 15.0

    notify_host: str = "0.0.0.0"
    notify_port: int = 8801

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> "BotSettings":
        if self.environment != "production":
            return self
        leftover = [
            field
            for field, insecure_value in _INSECURE_DEFAULTS.items()
            if getattr(self, field) == insecure_value
        ]
        if leftover:
            raise ValueError(
                "ENVIRONMENT=production but these settings still have their insecure "
                f"placeholder values from .env.example: {', '.join(sorted(leftover))}."
            )
        return self


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()
