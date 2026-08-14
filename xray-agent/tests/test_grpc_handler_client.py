"""End-to-end proof that GrpcXrayHandlerClient's vendored, trimmed proto subset (see
xray-agent/proto/ and docs/xray-agent.md) is actually wire-compatible: a real
grpc.aio server implementing HandlerService decodes exactly what GrpcXrayHandlerClient
sends (AddUserOperation/RemoveUserOperation wrapped in TypedMessage, VLESS Account
nested the same way) and its responses decode back correctly. This never talks to a
real Xray-core binary — the fake servicer here stands in for it, so this suite runs in
CI with no external dependency."""

import grpc
import grpc.aio
import pytest
import pytest_asyncio

from app.xray.handler_client import GrpcXrayHandlerClient, XrayCommandError
from app.xray_proto import command_pb2, command_pb2_grpc, vless_account_pb2

_ADD_TYPE = "xray.app.proxyman.command.AddUserOperation"
_REMOVE_TYPE = "xray.app.proxyman.command.RemoveUserOperation"
_ACCOUNT_TYPE = "xray.proxy.vless.Account"


class _FakeHandlerServicer(command_pb2_grpc.HandlerServiceServicer):
    def __init__(self) -> None:
        self.users: dict[str, str] = {}  # email -> uuid
        self.decoded_accounts: dict[str, tuple[str, str, str]] = {}
        self.fail_next = False

    def AlterInbound(self, request, context):  # noqa: N802 -- gRPC-generated method name
        if self.fail_next:
            self.fail_next = False
            context.abort(grpc.StatusCode.INTERNAL, "simulated Xray internal error")
        op_type = request.operation.type
        if op_type == _ADD_TYPE:
            op = command_pb2.AddUserOperation()
            op.ParseFromString(request.operation.value)
            assert op.user.account.type == _ACCOUNT_TYPE
            account = vless_account_pb2.Account()
            account.ParseFromString(op.user.account.value)
            self.users[op.user.email] = account.id
            self.decoded_accounts[op.user.email] = (account.id, account.flow, account.encryption)
        elif op_type == _REMOVE_TYPE:
            op = command_pb2.RemoveUserOperation()
            op.ParseFromString(request.operation.value)
            self.users.pop(op.email, None)
        else:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"unknown operation type {op_type}")
        return command_pb2.AlterInboundResponse()

    def GetInboundUsers(self, request, context):  # noqa: N802
        response = command_pb2.GetInboundUserResponse()
        for email in self.users:
            response.users.add(level=0, email=email)
        return response

    def GetInboundUsersCount(self, request, context):  # noqa: N802
        return command_pb2.GetInboundUsersCountResponse(count=len(self.users))


@pytest_asyncio.fixture
async def fake_xray_server():
    server = grpc.aio.server()
    servicer = _FakeHandlerServicer()
    command_pb2_grpc.add_HandlerServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    yield f"127.0.0.1:{port}", servicer
    await server.stop(None)


@pytest.mark.asyncio
async def test_add_user_reaches_real_servicer_with_correct_wire_format(fake_xray_server):
    address, servicer = fake_xray_server
    client = GrpcXrayHandlerClient(address, timeout_seconds=2.0)

    await client.add_user(
        tag="vless-reality-in",
        uuid="66ad4540-b58c-4ad2-9926-ea63445a9b57",
        email="device-1",
        flow="xtls-rprx-vision",
    )

    assert servicer.users["device-1"] == "66ad4540-b58c-4ad2-9926-ea63445a9b57"
    assert servicer.decoded_accounts["device-1"] == (
        "66ad4540-b58c-4ad2-9926-ea63445a9b57",
        "xtls-rprx-vision",
        "none",
    )


@pytest.mark.asyncio
async def test_remove_user_reaches_real_servicer(fake_xray_server):
    address, servicer = fake_xray_server
    client = GrpcXrayHandlerClient(address, timeout_seconds=2.0)
    await client.add_user(tag="t", uuid="u1", email="device-2", flow="xtls-rprx-vision")

    await client.remove_user(tag="t", email="device-2")

    assert "device-2" not in servicer.users


@pytest.mark.asyncio
async def test_list_and_count_users_round_trip(fake_xray_server):
    address, _ = fake_xray_server
    client = GrpcXrayHandlerClient(address, timeout_seconds=2.0)
    await client.add_user(tag="t", uuid="u1", email="device-3", flow="xtls-rprx-vision")
    await client.add_user(tag="t", uuid="u2", email="device-4", flow="xtls-rprx-vision")

    emails = await client.list_user_emails(tag="t")
    count = await client.count_users(tag="t")

    assert set(emails) == {"device-3", "device-4"}
    assert count == 2


@pytest.mark.asyncio
async def test_xray_error_response_is_wrapped_as_xray_command_error(fake_xray_server):
    address, servicer = fake_xray_server
    servicer.fail_next = True
    client = GrpcXrayHandlerClient(address, timeout_seconds=2.0)

    with pytest.raises(XrayCommandError):
        await client.add_user(tag="t", uuid="u1", email="device-5", flow="xtls-rprx-vision")


@pytest.mark.asyncio
async def test_xray_unreachable_is_wrapped_as_xray_command_error():
    # Nothing listening on this port — simulates Xray not yet started / crashed.
    client = GrpcXrayHandlerClient("127.0.0.1:1", timeout_seconds=1.0)

    with pytest.raises(XrayCommandError):
        await client.count_users(tag="vless-reality-in")
