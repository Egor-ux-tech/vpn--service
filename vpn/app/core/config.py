from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SHARED_SECRET = "change-me-vpn-agent-secret"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    agent_host: str = "0.0.0.0"
    agent_port: int = 8800

    vpn_agent_shared_secret: str = "change-me-vpn-agent-secret"
    signature_max_skew_seconds: int = 60

    wg_interface: str = "wg0"
    wg_config_path: str = "/etc/wireguard/wg0.conf"
    state_db_path: str = "/var/lib/vpn-agent/state.db"

    # Set to false only in local/dev/test where the `wg`/`ip` binaries and a real wg0
    # interface do not exist — the agent then tracks peer state without touching the OS.
    apply_to_live_interface: bool = True

    @model_validator(mode="after")
    def _reject_default_secret_in_production(self) -> "AgentSettings":
        if (
            self.environment == "production"
            and self.vpn_agent_shared_secret == _INSECURE_SHARED_SECRET
        ):
            raise ValueError(
                "ENVIRONMENT=production but VPN_AGENT_SHARED_SECRET is still the insecure "
                "placeholder from .env.example — set a real secret before starting in production."
            )
        return self


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
