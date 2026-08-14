import ipaddress

from app.core.errors import ConflictError
from app.repositories.vpn_peer_repository import VPNPeerRepository


async def allocate_ip(
    *, peer_repository: VPNPeerRepository, server_id: int, network_cidr: str
) -> str:
    """Pick the lowest free host address in `network_cidr` not already assigned on this
    server. Network/broadcast addresses and the first host (reserved for the server's own
    wg0 interface) are skipped."""
    network = ipaddress.ip_network(network_cidr, strict=False)
    existing_peers = await peer_repository.list_for_server(server_id)
    taken = {ipaddress.ip_address(p.assigned_ip.split("/")[0]) for p in existing_peers}

    hosts = network.hosts()
    next(hosts, None)  # reserve the first usable address for the server itself

    for candidate in hosts:
        if candidate not in taken:
            return f"{candidate}/32" if network.version == 4 else f"{candidate}/128"

    raise ConflictError(
        f"No free IP addresses left in {network_cidr} on server {server_id}",
        error_code="ip_pool_exhausted",
    )
