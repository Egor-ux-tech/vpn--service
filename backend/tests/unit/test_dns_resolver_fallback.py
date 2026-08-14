import dns.exception
import pytest

from app.services.routing.dns_resolver import DomainResolver


class _RaisingResolver:
    async def resolve(self, domain, rdtype):
        raise dns.exception.Timeout()


@pytest.mark.asyncio
async def test_resolve_falls_back_on_transient_dns_failure(monkeypatch):
    resolver = DomainResolver()
    monkeypatch.setattr(resolver, "_resolver", _RaisingResolver())

    ips = await resolver.resolve("flaky.example.com", fallback_ips=["1.2.3.4"])

    assert ips == ["1.2.3.4"]


@pytest.mark.asyncio
async def test_resolve_returns_empty_without_fallback_on_transient_failure(monkeypatch):
    resolver = DomainResolver()
    monkeypatch.setattr(resolver, "_resolver", _RaisingResolver())

    ips = await resolver.resolve("flaky.example.com")

    assert ips == []
