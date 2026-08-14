import pytest
from pydantic import ValidationError

from app.core.config import AgentSettings


def test_production_with_default_secret_is_rejected():
    with pytest.raises(ValidationError, match="insecure placeholder"):
        AgentSettings(
            environment="production", xray_agent_shared_secret="change-me-xray-agent-secret"
        )


def test_production_with_real_secret_is_accepted():
    settings = AgentSettings(
        environment="production", xray_agent_shared_secret="a-real-random-secret"
    )
    assert settings.environment == "production"


def test_development_allows_default_secret():
    settings = AgentSettings(
        environment="development", xray_agent_shared_secret="change-me-xray-agent-secret"
    )
    assert settings.xray_agent_shared_secret == "change-me-xray-agent-secret"
