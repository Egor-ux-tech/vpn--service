"""Resolves domains to IP ranges for Smart VPN AllowedIPs.

Design notes (see docs/routing.md for the full write-up):
- Both A and AAAA records are queried independently; a domain missing one family simply
  contributes no addresses for it, it does not fail the whole lookup.
- CDN-backed domains return multiple records — all of them are kept, not just the first.
- On a transient resolution failure (timeout, SERVFAIL, no nameservers) the caller-supplied
  `fallback_ips` are returned instead of an empty set, so a flaky DNS lookup never silently
  drops a domain out of the VPN routing table. A genuine NXDOMAIN (domain no longer exists)
  is treated as "no addresses," not a failure, since retrying won't help.
"""

import dns.asyncresolver
import dns.exception
import dns.rdatatype
import dns.resolver

from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 3.0


class DomainResolver:
    def __init__(self, nameservers: list[str] | None = None) -> None:
        self._resolver = dns.asyncresolver.Resolver()
        if nameservers:
            self._resolver.nameservers = nameservers
        self._resolver.timeout = _TIMEOUT_SECONDS
        self._resolver.lifetime = _TIMEOUT_SECONDS

    async def resolve(self, domain: str, fallback_ips: list[str] | None = None) -> list[str]:
        ips: list[str] = []
        had_transient_failure = False

        for rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA):
            try:
                answer = await self._resolver.resolve(domain, rdtype)
                ips.extend(str(rdata) for rdata in answer)
            except dns.resolver.NXDOMAIN:
                continue
            except dns.resolver.NoAnswer:
                continue
            except (dns.exception.Timeout, dns.resolver.NoNameservers, OSError) as exc:
                logger.warning("dns_resolve_transient_failure", domain=domain, error=str(exc))
                had_transient_failure = True

        if not ips and had_transient_failure and fallback_ips:
            return fallback_ips
        return ips
