import pytest
from pydantic import ValidationError

from app.core.config import AgentSettings


def test_production_with_default_secret_is_rejected():
    # conftest.py sets VPN_AGENT_SHARED_SECRET in the process environment for the rest of
    # this suite — pass the insecure value explicitly so this test isn't at the mercy of it.
    with pytest.raises(ValidationError, match="insecure placeholder"):
        AgentSettings(
            environment="production", vpn_agent_shared_secret="change-me-vpn-agent-secret"
        )


def test_production_with_real_secret_is_accepted():
    settings = AgentSettings(
        environment="production", vpn_agent_shared_secret="a-real-random-secret"
    )
    assert settings.environment == "production"


def test_development_allows_default_secret():
    settings = AgentSettings(
        environment="development", vpn_agent_shared_secret="change-me-vpn-agent-secret"
    )
    assert settings.vpn_agent_shared_secret == "change-me-vpn-agent-secret"
