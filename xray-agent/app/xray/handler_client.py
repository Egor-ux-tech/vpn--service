"""Talks to Xray-core's HandlerService gRPC API (loopback-only — see
app/core/config.py's xray_grpc_address and infrastructure/ansible/roles/xray) to add,
remove, and enumerate VLESS users on the live "vless-reality-in" inbound without ever
rewriting config.json or restarting the process.

`XrayHandlerClient` is the interface the rest of the agent depends on;
`GrpcXrayHandlerClient` is the real implementation, built against a trimmed,
wire-compatible subset of xray-core's own .proto files (vendored under xray-agent/proto/
— see docs/xray-agent.md's "gRPC integration" section for exactly what was vendored,
from where, and how the trimming was verified not to break wire compatibility). Tests
use an in-memory fake instead (see tests/conftest.py) — same shape as vpn-agent's
CommandRunner Protocol wrapping the `wg` CLI, so this module is fully unit-testable
without a real Xray process.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

import grpc

from app.core.metrics import XRAY_COMMAND_ERRORS_TOTAL
from app.xray_proto import (
    command_pb2,
    command_pb2_grpc,
    typed_message_pb2,
    user_pb2,
    vless_account_pb2,
)

_T = TypeVar("_T")

_ADD_USER_TYPE = "xray.app.proxyman.command.AddUserOperation"
_REMOVE_USER_TYPE = "xray.app.proxyman.command.RemoveUserOperation"
_VLESS_ACCOUNT_TYPE = "xray.proxy.vless.Account"

# VLESS's own `encryption` field is always "none" — encryption/obfuscation is provided
# entirely by the Reality/XTLS transport layer beneath it, not by this field. Verified
# against the official Happ-compatible example during the VLESS research spike; not
# configurable per user or per server.
_VLESS_ENCRYPTION = "none"


class XrayCommandError(RuntimeError):
    """Raised for any failure talking to Xray's gRPC API — connection refused (Xray
    down/not yet started), a malformed/unexpected response, or the RPC itself
    returning an error status. Never includes UUID/key material in its message."""


class XrayHandlerClient(Protocol):
    async def add_user(self, *, tag: str, uuid: str, email: str, flow: str) -> None: ...

    async def remove_user(self, *, tag: str, email: str) -> None: ...

    async def list_user_emails(self, *, tag: str) -> list[str]:
        """Returns every email currently live on the inbound — used by UserReconciler
        to diff desired vs. live state. Never returns UUIDs; Xray's GetInboundUsers
        response is not relied on to carry account details back out (this client
        never decodes the `account` field of a response User)."""
        ...

    async def count_users(self, *, tag: str) -> int:
        """A real round-trip to Xray's gRPC API — used as the liveness signal for
        GET /ready and GET /status (see api/health.py): confirms not just that the
        agent process is up, but that Xray itself is actually reachable."""
        ...


class GrpcXrayHandlerClient:
    def __init__(self, address: str, timeout_seconds: float = 5.0) -> None:
        self._address = address
        self._timeout = timeout_seconds

    def _stub(self) -> tuple[grpc.aio.Channel, command_pb2_grpc.HandlerServiceStub]:
        channel = grpc.aio.insecure_channel(self._address)
        return channel, command_pb2_grpc.HandlerServiceStub(channel)

    async def add_user(self, *, tag: str, uuid: str, email: str, flow: str) -> None:
        account = vless_account_pb2.Account(id=uuid, flow=flow, encryption=_VLESS_ENCRYPTION)
        user = user_pb2.User(
            level=0,
            email=email,
            account=typed_message_pb2.TypedMessage(
                type=_VLESS_ACCOUNT_TYPE, value=account.SerializeToString()
            ),
        )
        operation = command_pb2.AddUserOperation(user=user)
        request = command_pb2.AlterInboundRequest(
            tag=tag,
            operation=typed_message_pb2.TypedMessage(
                type=_ADD_USER_TYPE, value=operation.SerializeToString()
            ),
        )
        await self._call("add_user", lambda stub: stub.AlterInbound(request, timeout=self._timeout))

    async def remove_user(self, *, tag: str, email: str) -> None:
        operation = command_pb2.RemoveUserOperation(email=email)
        request = command_pb2.AlterInboundRequest(
            tag=tag,
            operation=typed_message_pb2.TypedMessage(
                type=_REMOVE_USER_TYPE, value=operation.SerializeToString()
            ),
        )
        await self._call(
            "remove_user", lambda stub: stub.AlterInbound(request, timeout=self._timeout)
        )

    async def list_user_emails(self, *, tag: str) -> list[str]:
        request = command_pb2.GetInboundUserRequest(tag=tag, email="")
        response = await self._call(
            "list_users", lambda stub: stub.GetInboundUsers(request, timeout=self._timeout)
        )
        return [u.email for u in response.users]

    async def count_users(self, *, tag: str) -> int:
        request = command_pb2.GetInboundUserRequest(tag=tag, email="")
        response = await self._call(
            "count_users", lambda stub: stub.GetInboundUsersCount(request, timeout=self._timeout)
        )
        return int(response.count)

    async def _call(
        self,
        operation: str,
        fn: Callable[[command_pb2_grpc.HandlerServiceStub], Awaitable[_T]],
    ) -> _T:
        channel, stub = self._stub()
        try:
            return await fn(stub)
        except grpc.RpcError as exc:
            XRAY_COMMAND_ERRORS_TOTAL.labels(operation=operation).inc()
            raise XrayCommandError(f"Xray gRPC call {operation!r} failed: {exc.code()}") from exc
        finally:
            await channel.close()
