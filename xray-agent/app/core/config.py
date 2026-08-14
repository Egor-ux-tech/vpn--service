from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SHARED_SECRET = "change-me-xray-agent-secret"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    agent_host: str = "0.0.0.0"
    agent_port: int = 8801

    # Deliberately its own secret, distinct from vpn-agent's VPN_AGENT_SHARED_SECRET —
    # compromising one node type's credential must not let an attacker reach the other
    # (see docs/xray-agent.md's security section).
    xray_agent_shared_secret: str = _INSECURE_SHARED_SECRET
    signature_max_skew_seconds: int = 60

    # Xray's HandlerService gRPC API — always loopback-only, never exposed beyond this
    # host (see infrastructure/ansible/roles/xray). xray-agent is the only process
    # allowed to reach it.
    xray_grpc_address: str = "127.0.0.1:10085"
    xray_inbound_tag: str = "vless-reality-in"
    xray_grpc_timeout_seconds: float = 5.0

    state_db_path: str = "/var/lib/xray-agent/state.db"

    # Xray-core has no equivalent of wg0.conf's SaveConfig=true — a crash-and-respawn
    # wipes its live user list with no local recovery, so xray-agent must reconcile
    # periodically, not just on its own startup (see app/xray/reconciler.py).
    reconciliation_interval_seconds: int = 300

    # Set to false only in local/dev/test where no real Xray process/gRPC endpoint
    # exists — the agent then tracks desired state without calling out.
    apply_to_live_xray: bool = True

    @model_validator(mode="after")
    def _reject_default_secret_in_production(self) -> "AgentSettings":
        if (
            self.environment == "production"
            and self.xray_agent_shared_secret == _INSECURE_SHARED_SECRET
        ):
            raise ValueError(
                "ENVIRONMENT=production but XRAY_AGENT_SHARED_SECRET is still the "
                "insecure placeholder from .env.example — set a real secret before "
                "starting in production."
            )
        return self


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
