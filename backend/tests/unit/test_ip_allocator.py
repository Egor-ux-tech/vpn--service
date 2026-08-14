import pytest

from app.core.errors import ConflictError
from app.services.vpn.ip_allocator import allocate_ip


class _FakePeer:
    def __init__(self, assigned_ip: str) -> None:
        self.assigned_ip = assigned_ip


class _FakePeerRepository:
    def __init__(self, peers: list[_FakePeer]) -> None:
        self._peers = peers

    async def list_for_server(self, server_id: int) -> list[_FakePeer]:
        return self._peers


@pytest.mark.asyncio
async def test_allocate_ip_skips_already_taken_addresses():
    # /29 = .0 network, .1 reserved for the server itself, .2-.6 usable hosts, .7 broadcast.
    repo = _FakePeerRepository([_FakePeer("10.66.0.2/32")])
    ip = await allocate_ip(peer_repository=repo, server_id=1, network_cidr="10.66.0.0/29")
    assert ip == "10.66.0.3/32"


@pytest.mark.asyncio
async def test_allocate_ip_raises_when_pool_exhausted():
    # /30 leaves exactly one assignable host after reserving .1 for the server — take it.
    repo = _FakePeerRepository([_FakePeer("10.66.0.2/32")])
    with pytest.raises(ConflictError):
        await allocate_ip(peer_repository=repo, server_id=1, network_cidr="10.66.0.0/30")
