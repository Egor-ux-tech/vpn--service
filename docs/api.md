# API Reference

The backend exposes a REST API under `/api/v1`. This document covers the shape of the API
— auth model, conventions, endpoint groups. For the exhaustive, always-current parameter
list, run the backend locally and open `/docs` (Swagger UI, enabled outside
`ENVIRONMENT=production`) — schemas here would drift from the actual Pydantic models over
time; the OpenAPI schema generated from those same models cannot.

## Authentication models

The API has three distinct callers, each authenticated differently:

| Caller | Mechanism | Header(s) |
|---|---|---|
| Telegram bot, acting on behalf of a user | Internal service token + the acting user's Telegram ID | `X-Internal-Token`, `X-Telegram-User-Id` |
| Admin panel | JWT Bearer token (from `/auth/admin/login`) | `Authorization: Bearer <token>` |
| Payment provider webhook | HMAC signature over the raw request body | `X-Signature` |
| vpn-agent (separate service, not part of this API) | HMAC signature + timestamp | `X-Signature`, `X-Timestamp` |

The bot never receives a per-user token — Telegram itself already authenticated the human
before an update reaches the bot, so the bot only needs to prove *it* is the trusted bot
(`X-Internal-Token`, compared with `hmac.compare_digest`) and say *which* user it's acting
for (`X-Telegram-User-Id`). See `backend/app/core/deps.py::get_current_user`.

Admin endpoints are additionally role-gated (`AdminRole.SUPERADMIN` / `SUPPORT` / `VIEWER`)
— see `require_admin_role(...)` on each route for the roles it accepts.

## Conventions

- All request/response bodies are JSON.
- Errors follow one shape:
  ```json
  {"error": {"code": "device_limit_reached", "message": "...", "details": null, "request_id": "..."}}
  ```
  `code` is a stable machine-readable string (match on this, not `message`, which is
  free text and may change). `request_id` correlates with the structured log line for that
  request (see `X-Request-ID` response header).
- List endpoints take `offset`/`limit` query params (see `Pagination` schema); none are
  cursor-paginated in the MVP.
- Rate limiting: a default of `RATE_LIMIT_DEFAULT` (100/minute per client IP) applies to
  every endpoint; `/auth/admin/login` and `/auth/admin/bootstrap` have stricter,
  endpoint-specific limits (brute-force targets — see `app/core/rate_limit.py`).

## Endpoint groups

| Prefix | Purpose |
|---|---|
| `/auth` | Telegram upsert (bot-only), admin login, one-time admin bootstrap |
| `/users` | Self profile (`/me`); admin: list/get/block users |
| `/plans` | Public plan catalog; admin: create/update plans |
| `/subscriptions` | Own subscription history/active status, cancel |
| `/devices` | Provision/list/reissue/disable/enable/revoke the caller's own devices |
| `/vpn` | Current routing profile (AllowedIPs/DNS) for a device, on-demand refresh |
| `/servers` | Public server list; admin: create/update/delete |
| `/routing` | Public category catalog; own Smart VPN mode/categories/custom domains; admin: manage the domain catalog |
| `/payments` | Create a payment, own payment history, provider webhook, admin: list all / refund |
| `/support` | Create/view own tickets and messages; admin: list all, reply, close |
| `/admin` | Dashboard aggregate stats, audit log |

## Notable request/response flows

**Device provisioning** (`POST /devices`) returns the WireGuard config and a QR code
**exactly once** — the private key is generated on the vpn-agent, forwarded through the
backend without being persisted, and handed to the caller in this single response. There is
no "re-fetch my config" endpoint; `POST /devices/{id}/reissue` rotates to a brand-new
keypair instead (see docs/wireguard.md).

**Payments** (`POST /payments`) never activates a subscription directly — it returns a
`checkout_url`/pending status, and only `POST /payments/webhook`, signature-verified and
idempotent by `external_payment_id`, transitions the subscription to `active` (see
`PaymentService.handle_webhook`).

**Smart VPN** (`GET/PUT /routing/me/*`) lets a user pick `full_vpn` vs `smart_vpn`, toggle
catalog categories, and add custom domains; the resulting `AllowedIPs` set is computed by
`POST /vpn/devices/{id}/profile/refresh` (see docs/routing.md for how domains resolve to
IP ranges).
