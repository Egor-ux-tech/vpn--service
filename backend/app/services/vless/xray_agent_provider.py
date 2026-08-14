"""HttpXrayAgentProvider — talks to the `xray-agent` service running on each VLESS
VPNServer. Same HMAC-signing shape as `app.services.vpn.wireguard_provider.
WireGuardProvider` (see that module's docstring for the security rationale), signed with
`XRAY_AGENT_SHARED_SECRET` — a secret deliberately distinct from `VPN_AGENT_SHARED_SECRET`
(see app/core/config.py) so a compromised credential for one node type cannot be
replayed against the other.

Every mutating call here (create/remove/rotate) is idempotent on xray-agent's side (see
xray-agent's app/api/users.py), which is what makes the bounded retry in `_request` safe:
a retried create/remove/rotate can never double-provision or double-delete a user.
"""

import asyncio
import time
from datetime import datetime

import httpx
import orjson

from app.core.errors import ExternalServiceError
from app.core.logging import get_logger
from app.core.metrics import VLESS_PROVISIONING_ERRORS_TOTAL
from app.core.security import sign_hmac
from app.models.vless_server_config import VLESSServerConfig
from app.services.vless.provider import VLESSUserRecord

logger = get_logger(__name__)

_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5


class HttpXrayAgentProvider:
    def __init__(self, shared_secret: str, timeout_seconds: float = 10.0) -> None:
        self._shared_secret = shared_secret
        self._timeout = timeout_seconds

    async def _request(self, base_url: str, method: str, path: str, payload: dict) -> dict | list:
        body = orjson.dumps(payload)
        signature = sign_hmac(body, self._shared_secret)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Timestamp": str(int(time.time())),
        }
        url = f"{base_url.rstrip('/')}{path}"

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(method, url, content=body, headers=headers)
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.TransportError as exc:
                # Connection-level only (refused/timeout/reset) — safe to retry because
                # every call this method serves is idempotent on xray-agent's side.
                # httpx.HTTPStatusError (a 4xx/5xx that actually reached the agent) is
                # deliberately NOT retried here — see the except clause below.
                last_error = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
            except httpx.HTTPError as exc:
                logger.error(
                    "xray_agent_request_failed", base_url=base_url, path=path, error=str(exc)
                )
                VLESS_PROVISIONING_ERRORS_TOTAL.labels(operation=path).inc()
                raise ExternalServiceError(
                    f"xray-agent request failed for {base_url}",
                    error_code="xray_agent_unreachable",
                ) from exc

        logger.error(
            "xray_agent_request_failed",
            base_url=base_url,
            path=path,
            error=str(last_error),
            attempts=_MAX_ATTEMPTS,
        )
        VLESS_PROVISIONING_ERRORS_TOTAL.labels(operation=path).inc()
        raise ExternalServiceError(
            f"xray-agent request failed for {base_url} after {_MAX_ATTEMPTS} attempts",
            error_code="xray_agent_unreachable",
        ) from last_error

    @staticmethod
    def _to_record(data: dict) -> VLESSUserRecord:
        rotated_at = data.get("rotated_at")
        return VLESSUserRecord(
            uuid=data["uuid"],
            device_id=data["device_id"],
            flow=data["flow"],
            created_at=datetime.fromisoformat(data["created_at"]),
            rotated_at=datetime.fromisoformat(rotated_at) if rotated_at else None,
        )

    async def create_user(
        self, *, server_config: VLESSServerConfig, uuid: str, device_id: int, flow: str
    ) -> VLESSUserRecord:
        data = await self._request(
            server_config.xray_agent_base_url,
            "POST",
            "/users",
            {"uuid": uuid, "device_id": device_id, "flow": flow},
        )
        assert isinstance(data, dict)
        return self._to_record(data)

    async def remove_user(self, *, server_config: VLESSServerConfig, uuid: str) -> None:
        await self._request(server_config.xray_agent_base_url, "DELETE", f"/users/{uuid}", {})

    async def rotate_user(
        self, *, server_config: VLESSServerConfig, uuid: str, new_uuid: str
    ) -> VLESSUserRecord:
        data = await self._request(
            server_config.xray_agent_base_url,
            "POST",
            f"/users/{uuid}/rotate",
            {"new_uuid": new_uuid},
        )
        assert isinstance(data, dict)
        return self._to_record(data)

    async def list_users(self, *, server_config: VLESSServerConfig) -> list[VLESSUserRecord]:
        data = await self._request(server_config.xray_agent_base_url, "GET", "/users", {})
        assert isinstance(data, list)
        return [self._to_record(item) for item in data]

    async def health_check(self, *, server_config: VLESSServerConfig) -> bool:
        url = f"{server_config.xray_agent_base_url.rstrip('/')}/ready"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # /ready is deliberately unauthenticated on xray-agent (same as
                # vpn-agent's own /health, /ready, /metrics) — no HMAC needed here.
                response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError:
            return False
        return bool(data.get("xray_reachable", False))
