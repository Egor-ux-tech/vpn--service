"""Thin async HTTP client for the backend API. The bot has no business logic of its own —
every rule (device limits, subscription state, routing preferences) lives in the backend so
the bot, the admin panel, and any future client share exactly one implementation.

Telegram has already authenticated the human by the time an update reaches this bot, so
every call here is trusted-service-to-service: it carries the shared `X-Internal-Token` plus
`X-Telegram-User-Id` to tell the backend which user is acting.
"""

from typing import Any

import httpx

from app.core.config import BotSettings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BackendError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class BackendClient:
    def __init__(self, settings: BotSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.backend_api_base_url, timeout=settings.request_timeout_seconds
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self, telegram_id: int | None) -> dict[str, str]:
        headers = {"X-Internal-Token": self._settings.internal_service_token}
        if telegram_id is not None:
            headers["X-Telegram-User-Id"] = str(telegram_id)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        telegram_id: int | None = None,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        response = await self._client.request(
            method, path, headers=self._headers(telegram_id), json=json, params=params
        )
        if response.status_code >= 400:
            try:
                body = response.json()
                error = body.get("error", {})
                error_code = error.get("code", "unknown_error")
                message = error.get("message", response.text)
            except ValueError:
                error_code = "unknown_error"
                message = response.text
            raise BackendError(response.status_code, error_code, message)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ---- Auth / profile ----

    async def authenticate(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> dict:
        return await self._request(
            "POST",
            "/api/v1/auth/telegram",
            json={
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
            },
        )

    async def get_me(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/v1/users/me", telegram_id=telegram_id)

    # ---- Plans / subscriptions ----

    async def list_plans(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/api/v1/plans", telegram_id=telegram_id)

    async def get_active_subscription(self, telegram_id: int) -> dict | None:
        return await self._request(
            "GET", "/api/v1/subscriptions/me/active", telegram_id=telegram_id
        )

    async def cancel_subscription(self, telegram_id: int, subscription_id: int) -> dict:
        return await self._request(
            "POST", f"/api/v1/subscriptions/{subscription_id}/cancel", telegram_id=telegram_id
        )

    # ---- Payments ----

    async def create_payment(
        self, telegram_id: int, plan_id: int, promo_code: str | None = None
    ) -> dict:
        return await self._request(
            "POST",
            "/api/v1/payments",
            telegram_id=telegram_id,
            json={"plan_id": plan_id, "promo_code": promo_code},
        )

    # ---- Devices ----

    async def list_devices(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/api/v1/devices", telegram_id=telegram_id)

    async def create_device(
        self, telegram_id: int, name: str, server_id: int | None = None
    ) -> dict:
        return await self._request(
            "POST",
            "/api/v1/devices",
            telegram_id=telegram_id,
            json={"name": name, "server_id": server_id},
        )

    async def reissue_device(self, telegram_id: int, device_id: int) -> dict:
        return await self._request(
            "POST", f"/api/v1/devices/{device_id}/reissue", telegram_id=telegram_id
        )

    async def disable_device(self, telegram_id: int, device_id: int) -> dict:
        return await self._request(
            "POST", f"/api/v1/devices/{device_id}/disable", telegram_id=telegram_id
        )

    async def enable_device(self, telegram_id: int, device_id: int) -> dict:
        return await self._request(
            "POST", f"/api/v1/devices/{device_id}/enable", telegram_id=telegram_id
        )

    async def revoke_device(self, telegram_id: int, device_id: int) -> dict:
        return await self._request(
            "DELETE", f"/api/v1/devices/{device_id}", telegram_id=telegram_id
        )

    # ---- Servers ----

    async def list_servers(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/api/v1/servers", telegram_id=telegram_id)

    # ---- Routing / Smart VPN ----

    async def get_routing_settings(self, telegram_id: int) -> dict:
        return await self._request("GET", "/api/v1/routing/me/settings", telegram_id=telegram_id)

    async def set_routing_mode(self, telegram_id: int, mode: str) -> dict:
        return await self._request(
            "PUT", "/api/v1/routing/me/mode", telegram_id=telegram_id, json={"mode": mode}
        )

    async def set_category_preference(
        self, telegram_id: int, category_id: int, enabled: bool
    ) -> dict:
        return await self._request(
            "PUT",
            "/api/v1/routing/me/categories",
            telegram_id=telegram_id,
            json={"category_id": category_id, "enabled": enabled},
        )

    async def add_custom_domain(
        self, telegram_id: int, domain: str, route_type: str = "vpn"
    ) -> dict:
        return await self._request(
            "POST",
            "/api/v1/routing/me/domains",
            telegram_id=telegram_id,
            json={"domain": domain, "route_type": route_type},
        )

    # ---- Support ----

    async def create_support_ticket(self, telegram_id: int, subject: str, message: str) -> dict:
        return await self._request(
            "POST",
            "/api/v1/support",
            telegram_id=telegram_id,
            json={"subject": subject, "message": message},
        )

    async def list_support_tickets(self, telegram_id: int) -> list[dict]:
        return await self._request("GET", "/api/v1/support/me", telegram_id=telegram_id)
