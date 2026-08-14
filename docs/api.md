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
| xray-agent (separate service, not part of this API — see docs/xray-agent.md) | HMAC signature + timestamp, distinct secret from vpn-agent's | `X-Signature`, `X-Timestamp` |
| VPN client fetching a subscription (`GET /sub/{token}`, **not** under `/api/v1`) | The 256-bit bearer token *is* the credential — no header, it's the path itself | — |

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
| `/devices/{id}/subscription-link` | Create-or-rotate / view metadata / revoke the caller's own subscription link — see docs/subscription-delivery.md |
| `/vpn` | Current routing profile (AllowedIPs/DNS) for a device, on-demand refresh |
| `/servers` | WireGuard server list (public); admin: create/update/delete |
| `/vless-servers` | Admin-only: create/list/update/delete VLESS exit nodes — see docs/vless.md |
| `/routing` | Public category catalog; own Smart VPN mode/categories/custom domains; admin: manage the domain catalog |
| `/payments` | Create a payment, own payment history, provider webhook, admin: list all / refund |
| `/support` | Create/view own tickets and messages; admin: list all, reply, close |
| `/admin` | Dashboard aggregate stats, audit log |

`/sub/{token}` is **not** under `/api/v1` — it's the public subscription-delivery endpoint
(see docs/subscription-delivery.md), mounted directly on the app since it isn't part of the
authenticated JSON API surface at all.

## Notable request/response flows

**Device provisioning** (`POST /devices`, body includes `protocol: "wireguard" | "vless"`,
defaulting to `"wireguard"`) returns the WireGuard config and a QR code **exactly once**
for `protocol=wireguard` — the private key is generated on the vpn-agent, forwarded
through the backend without being persisted, and handed to the caller in this single
response. There is no "re-fetch my private key" endpoint; `POST /devices/{id}/reissue`
rotates to a brand-new keypair instead (see docs/wireguard.md) — and is rejected outright
(422, `reissue_not_supported_for_protocol`) for VLESS devices, since there is no
per-provisioning artifact to re-issue there (see below). The same response also includes a
`subscription_url` (and its own QR) for the device's auto-created subscription link — that
one *is* re-fetchable later via `GET /sub/{token}`, just without a private key in it (see
docs/subscription-delivery.md for why).

For `protocol=vless`, `config_text`/`qr_code_base64` are `null` — there is no separate
downloadable artifact; the subscription link fetched live via `GET /sub/{token}` *is* the
config. See docs/vless.md for the full data flow and docs/xray-agent.md for the node-side
service that actually provisions the VLESS user.

**Subscription links** (`GET /sub/{token}`) are the repeatedly-fetchable counterpart to the
one-time provisioning response above. The token is bearer-auth by itself (no header), so
every failure mode — never issued, revoked, billing lapsed, device disabled — returns the
identical generic 404; see docs/subscription-delivery.md for the full security model.

**Payments** (`POST /payments`) never activates a subscription directly — it returns a
`checkout_url`/pending status, and only `POST /payments/webhook`, signature-verified and
idempotent by `external_payment_id`, transitions the subscription to `active` (see
`PaymentService.handle_webhook`).

**Smart VPN** (`GET/PUT /routing/me/*`) lets a user pick `full_vpn` vs `smart_vpn`, toggle
catalog categories, and add custom domains; the resulting `AllowedIPs` set is computed by
`POST /vpn/devices/{id}/profile/refresh` (see docs/routing.md for how domains resolve to
IP ranges).
