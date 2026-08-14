"""Builds a WireGuard AllowedIPs set from routing rules.

No custom protocol/traffic-inspection is implemented: split tunneling is achieved purely
through WireGuard's own AllowedIPs mechanism (see docs/architecture.md section 4).
"""

import ipaddress

from app.models.enums import RouteType
from app.services.routing.dns_resolver import DomainResolver

DomainRule = tuple[str, RouteType]  # (domain, route_type)


class RoutingEngine:
    def __init__(self, resolver: DomainResolver) -> None:
        self._resolver = resolver

    async def build_allowed_ips(
        self,
        rules: list[DomainRule],
        *,
        previous_ips_by_domain: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Resolves every domain with route_type=VPN and returns a de-duplicated,
        aggregated CIDR list suitable for a peer's AllowedIPs. DIRECT-routed domains are
        never resolved into this list — they are simply left off, so the client's own
        default route (outside the tunnel) handles them."""
        previous_ips_by_domain = previous_ips_by_domain or {}
        networks: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()

        for domain, route_type in rules:
            if route_type is not RouteType.VPN:
                continue
            ips = await self._resolver.resolve(
                domain, fallback_ips=previous_ips_by_domain.get(domain)
            )
            for ip in ips:
                try:
                    addr = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                prefix = 32 if addr.version == 4 else 128
                networks.add(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))

        v4 = [n for n in networks if n.version == 4]
        v6 = [n for n in networks if n.version == 6]
        collapsed = list(ipaddress.collapse_addresses(v4)) + list(ipaddress.collapse_addresses(v6))
        return sorted(str(n) for n in collapsed)

    @staticmethod
    def full_vpn_allowed_ips() -> list[str]:
        return ["0.0.0.0/0", "::/0"]
