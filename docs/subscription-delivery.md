# Subscription Delivery (Phase 1)

> **Update**: `HappFormatter` for WireGuard remains unimplemented for the reason stated
> below (Happ does not officially support WireGuard — see the research this established).
> VLESS+Reality was subsequently implemented as a second, parallel protocol *and* Happ
> client target, with its own `VLESSFormatter` — see [`docs/vless.md`](vless.md). The
> token/security/delivery layer this document describes (`SubscriptionLinkService`,
> `SubscriptionDeliveryService`, the anti-enumeration generic-404 property) is unchanged
> and reused as-is for VLESS; only a new formatter dispatch path was added. The rest of
> this document describes the original WireGuard-only Phase 1 as shipped, kept for
> historical/design context.

A **subscription link** is a stable, repeatedly-fetchable URL a VPN client uses to pull a
device's current config — `GET /sub/{token}`. This is a distinct concept from a
`Subscription` (the billing entity in `app/models/subscription.py`, `/api/v1/subscriptions`)
and the naming is kept deliberately separate everywhere in the code (`SubscriptionLink`,
`SubscriptionLinkService`, `SubscriptionDeliveryService`) to avoid the two being confused —
"subscription" here means the VPN-industry term (the same one Xray/V2Ray/Clash/Happ-style
panels use), not "the user is subscribed to the service."

This is **Phase 1** of a larger design (see the architecture proposal this implements).
Explicitly out of scope for this phase, by instruction:

- **HappFormatter** — Happ's actual subscription wire format has not been verified against
  a real install, so nothing Happ-specific is implemented. Only `WireGuardFormatter` exists.
- **vpn-agent changes** — the WireGuard peer lifecycle (`vpn/`) is completely untouched.
- **Client-generated WireGuard keys** — every key is still generated server-side, exactly
  as before.
- **Multi-node aggregation** — one link maps to exactly one device/peer, matching the
  existing 1:1 device model. A subscription URL does not fan out across multiple servers.

## The private-key limitation (read this before assuming `/sub/{token}` "just works")

This service has never persisted WireGuard private keys (see `docs/wireguard.md`) — a
key is generated on the vpn-agent, forwarded through the backend exactly once in a
provisioning/reissue response, and never written to the database. **This is unchanged.**

A subscription link, by design, can be fetched again later, by a process that never saw
the original provisioning response. That later fetch **cannot** include a real private
key — it was never stored anywhere to retrieve. `WireGuardFormatter` reflects this
honestly: the config it renders for `GET /sub/{token}` has a working `[Interface]`
`Address`/`DNS` and a working `[Peer]` section, but its `PrivateKey` line is replaced with
an explanatory comment instead of a fabricated or stale value.

In other words: **`/sub/{token}` is fully functional for everything except the one field a
real WireGuard client needs to actually connect.** This is a known, deliberate Phase 1
gap, not a bug. Closing it requires a decision between two options, both intentionally
deferred:

1. **Move key generation to the client** — the VPN client (Happ or a WireGuard app)
   generates its own keypair locally and sends only the public key when activating a
   device. The backend/vpn-agent then only ever handle a public key for that peer, exactly
   like today's trust model. This needs one small, additive, backward-compatible change to
   vpn-agent's peer-create endpoint (accept an optional caller-supplied public key) —
   explicitly deferred ("do not change vpn-agent yet").
2. **Persist an encrypted private key**, scoped only to subscription-delivered peers,
   decrypted at serve time. A real security-posture change (expands what a DB+key
   compromise exposes) — not recommended unless option 1 turns out to be unworkable for
   Happ's actual onboarding flow. Not implemented.

Until one of these lands, `/sub/{token}`'s practical use is: proving the delivery pipeline
end-to-end, and formats that don't need a WireGuard private key at all (a future
sing-box/VLESS-style formatter would not have this limitation, since those protocols
already expect the client to hold its own key material independent of the server).

## Token lifecycle

- **Creation**: automatic, the moment a device is provisioned (`DeviceService.provision`
  calls `SubscriptionLinkService.create_or_rotate` right after the `Device` row exists).
- **Format**: `secrets.token_urlsafe(32)` — 256 bits of randomness, opaque (not a JWT: a
  JWT is self-describing and can't be cleanly revoked without a blocklist; this needs to be
  revocable by a plain DB flip).
- **Storage**: only `sha256(token)` is ever persisted (`subscription_links.token_hash`),
  plus a non-secret 8-character `token_prefix` for support/log reference. The plaintext
  exists only in memory, only at creation/rotation time — there is no way to recover or
  re-display it later, by design (mirrors how a WireGuard private key is handled).
- **Verification**: hash the incoming token, look it up by the (indexed, unique) hash
  column. This — not bcrypt/argon2 — is the correct approach for a high-entropy bearer
  token: a slow password hash defends against *low-entropy* secrets a human might choose;
  this token already has 256 bits of entropy from `secrets.token_urlsafe`, and a plain
  SHA-256-then-indexed-lookup gives no attacker-observable timing signal tied to a guess,
  since the only comparison happening is a hash-keyed DB lookup, not a variable-time
  comparison against the guess itself.
- **Rotation**: `POST /api/v1/devices/{device_id}/subscription-link` — creates a link if
  the device has none yet, or generates a brand-new token if it does (old one dies
  immediately, in the same operation). One endpoint serves both the bootstrap case and the
  user-facing "regenerate my link" action.
- **Revocation**: `DELETE /api/v1/devices/{device_id}/subscription-link` — soft (`status =
  revoked`, timestamped), not a row deletion, consistent with how `Device`/`VPNPeer`
  already use status enums.
- **Expiration**: not a link-level TTL. `GET /sub/{token}` re-validates the underlying
  billing `Subscription` is `ACTIVE` and unexpired on *every* fetch — a link for a lapsed
  subscription simply stops resolving, no separate expiry clock needed.

## Database changes

One new table, one new enum — nothing else in the schema changed.

```
subscription_links
  id                 PK
  device_id          FK -> devices.id, UNIQUE (1:1 with Device in Phase 1), CASCADE delete
  token_hash         sha256 hex, UNIQUE, indexed
  token_prefix       8 chars, non-secret
  status             SubscriptionLinkStatus: active | revoked
  rotated_at         nullable
  revoked_at         nullable
  last_accessed_at   nullable, updated on every successful GET /sub/{token}
  access_count       incremented on every successful fetch
  created_at / updated_at   (TimestampMixin, same as every other model)
```

Migration: `dfef610f2c74_add_subscription_links.py` (down_revision:
`3073258ed68f`, the IP-allocation unique-constraint migration). A plain `create_table`, no
`batch_alter_table` needed (that's only required for *altering* an existing table on
SQLite) — verified upgrade/downgrade/upgrade round-trip against SQLite locally.

## API endpoints

**Authenticated management** (bot-trust path — `X-Internal-Token` + `X-Telegram-User-Id`,
same as every other `/api/v1/devices/*` endpoint), mounted under the existing device
resource:

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/v1/devices/{device_id}/subscription-link` | Create-or-rotate. Returns the plaintext URL + a QR code — the only response that ever does. |
| `GET` | `/api/v1/devices/{device_id}/subscription-link` | Metadata only (status, prefix, timestamps) — never the token/URL itself, since only the hash is stored. 404 (`subscription_link_not_found`) if none exists yet. |
| `DELETE` | `/api/v1/devices/{device_id}/subscription-link` | Revoke. |

All three enforce device ownership exactly like the existing device endpoints
(`DeviceService.get_owned`) — another user's `device_id` 404s, not 403, so it doesn't
confirm the device exists at all.

**Public delivery** (mounted directly on the app, *not* under `/api/v1` — see
`app/api/sub.py` and `app/main.py`):

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/sub/{token}` | Resolves the token, re-authorizes everything from scratch, renders via the selected formatter. |

No `X-Internal-Token`/JWT here — the token in the path *is* the credential, matching every
existing subscription-panel convention (Marzban, 3x-ui, Xray, ...) that a client like Happ
already expects a short, copy-pasteable, top-level URL for.

## Service-layer architecture

```
SubscriptionLinkService       — token lifecycle only: create/rotate/revoke/resolve.
                                 Does not decide *whether* access is currently allowed.
SubscriptionDeliveryService   — orchestrates GET /sub/{token}: resolve -> re-check
                                 billing subscription + device + peer state -> pick a
                                 formatter -> render. Every failure raises the exact same
                                 NotFoundError.
SubscriptionFormatter (Protocol) — the extension point. WireGuardFormatter is the only
                                 implementation today.
```

`SubscriptionLinkService` and `SubscriptionDeliveryService` are a deliberate split: a link
can be a perfectly valid *token* while the billing subscription behind it has lapsed, or
the device has been disabled — token validity and access authorization are different
questions, and only the delivery service re-checks the second one on every single request
(not just at link-creation time).

Nothing about `DeviceService`, `RoutingService`, or `WireGuardProvider`'s peer-lifecycle
methods changed — the new layer is a read/compose layer in front of state those already
produce. The one relocation: `WireGuardProvider.build_client_config`'s actual rendering
logic moved into `render_wireguard_config` (a shared pure function, importable by both the
provider and `WireGuardFormatter`) — `build_client_config`'s own signature and behavior for
existing callers (`DeviceService.provision`/`reissue`) are unchanged.

## Formatter abstraction

```python
class SubscriptionFormatter(Protocol):
    format_id: str
    content_type: str
    async def render(self, *, device, peer, server, profile) -> bytes: ...
```

`format_id` is selected via `?format=` (explicit, e.g. `/sub/{token}?format=wireguard`);
an unrecognized or omitted value falls back to the default (`wireguard`) rather than
erroring — a typo'd query param must never produce a response indistinguishable from "bad
token." No User-Agent sniffing is implemented in Phase 1 (that would require assumptions
about what UA strings Happ and others actually send, which is exactly the kind of
Happ-specific guessing this phase avoids).

Adding a future client/format is a new class registered in
`get_subscription_formatters()` (`app/core/deps.py`) — nothing else in the token/security/
delivery layers changes.

## Security model

- **Token security**: see "Token lifecycle" above — 256-bit opaque, hashed at rest, never
  logged.
- **Path masking**: `GET /sub/{token}` embeds the credential directly in the URL path, so
  `request.url.path` is not safe to log verbatim the way it is for every other route.
  `app/core/logging.py::safe_request_path` masks it to `/sub/***` before it reaches
  `RequestContextMiddleware`'s `request_completed` log line or either of
  `app/core/errors.py`'s `app_error`/`unhandled_exception` log lines — the three places a
  request path is logged. Verified with a real request through the full middleware stack
  and `capsys`, not just a unit test of the masking function in isolation.
- **Log redaction**: `config_text` (a rendered config is exactly as sensitive as the
  private key it might contain), `subscription_token`, and `subscription_url` were added
  to the backend's `_REDACT_KEYS` (`app/core/logging.py`) and the bot's own
  (`bot/app/core/logging.py`), for defense in depth if a future log call ever passes one of
  these as a field — nothing in the current code actually does (grepped and confirmed no
  `logger.*` call anywhere in the new subscription-link code touches the token or a
  rendered config).
- **Rate limiting**: `GET /sub/{token}` has its own limit
  (`settings.subscription_link_rate_limit`, default `30/minute`), stricter than the general
  API default, applied via the existing Redis-backed `slowapi` limiter (including its
  in-memory fallback if Redis is briefly unreachable — see `app/core/rate_limit.py`). Keyed
  by client IP, same as every other rate-limited route; there is no authenticated identity
  to key on for this endpoint.
- **Enumeration resistance**: every failure mode — token never issued, revoked, billing
  lapsed, device disabled, device revoked, peer not usable — returns the *exact same*
  `{"error": {"code": "not_found", "message": "Not found", ...}}` body at the exact same
  404 status. A test (`test_all_failure_modes_produce_byte_identical_responses`) proves two
  genuinely different failure causes produce byte-identical bodies (aside from the
  per-request `request_id`).
- **No internal IDs leaked unnecessarily**: `SubscriptionLinkRead` (the management
  endpoints' response shape) omits the link's own database `id` — the caller already knows
  `device_id` (it's in the URL), and the link's own PK serves no purpose to a client.
- **Revocation is synchronous**: no caching layer sits in front of the token-resolution
  query in Phase 1, so revoking takes effect on the very next request. Worth remembering as
  a constraint if a cache is ever added for performance later.

## Telegram exposure

- After provisioning a new device, the bot sends the subscription link as a copyable
  `<code>` block plus its own QR code (reusing the existing generic `qrcode_util.py`),
  right after the existing WireGuard QR/config file. `reissue()` never triggers this — it
  doesn't touch the subscription link (see `ProvisionedDevice`'s docstring in
  `device_service.py`).
- A "🔗 Ссылка подписки" button on the existing device-management keyboard opens a
  view/rotate screen: view shows status/prefix/created-at (never the token itself, per the
  hash-only storage above); rotate calls the same create-or-rotate endpoint and re-sends
  the link + QR.

## Configuration

- `SUBSCRIPTION_BASE_URL` — the public origin used to build `<base>/sub/{token}` links.
  **Never hardcoded.** Must be the real `https://<API_DOMAIN>` origin in production (the
  same one Caddy terminates TLS for) — required, not defaulted, in
  `docker-compose.prod.yml` (fails fast via `${SUBSCRIPTION_BASE_URL:?...}` if left unset),
  since a silently-defaulted `localhost` value would hand every real user a dead link.
- `SUBSCRIPTION_LINK_RATE_LIMIT` — see "Security model" above.

## Testing

**Covered locally** (see `backend/tests/unit/test_subscription_token_security.py`,
`test_wireguard_formatter.py`, `backend/tests/integration/test_subscription_links.py`,
`test_subscription_delivery.py`, and `bot/tests/test_backend_client_subscription_link.py`,
`test_subscription_link_handlers.py`): token generation/hashing/entropy, resolution,
rotation and old-token invalidation, revocation, every `/sub/{token}` failure mode and
their byte-identical shape, rate limiting against the real configured threshold, log
redaction against real request/log output (not a mock), `WireGuardFormatter` output with
and without a private key, provisioning auto-creating a link, and the bot's Telegram
delivery/callback flow.

**Only verifiable on a real device**: whether a real WireGuard client (or, later, Happ)
actually behaves sensibly when handed a config with no `PrivateKey` line — this sandbox has
no real WireGuard client to test against, matching the same limitation documented in
`docs/PRODUCTION_READINESS.md` for the rest of this project's WireGuard-facing surface.

## Remaining Happ-specific questions (blocking Phase 2)

1. **What wire format does Happ's subscription import actually expect?** A WireGuard URI
   scheme, a sing-box-style JSON config, Happ's own proprietary format, or something else —
   unverified. Blocks `HappFormatter` entirely.
2. **Does Happ's WireGuard onboarding accept a client-generated private key**, or does it
   expect the server to hand it one? This decides whether option 1 or option 2 (see "The
   private-key limitation" above) is the right way to make `/sub/{token}` deliver a fully
   working WireGuard config.
3. **What User-Agent string(s) does Happ actually send**, if format auto-detection via UA
   sniffing is ever added on top of the explicit `?format=` parameter.
4. **Does Happ expect specific subscription response headers** (e.g. a
   `subscription-userinfo` header some panels use for traffic-quota display, a
   `profile-title` header for the display name shown in-app)? Unknown; not implemented.
5. **Polling behavior** — how often a real Happ install re-fetches a subscription URL in
   practice, needed to sanely calibrate `SUBSCRIPTION_LINK_RATE_LIMIT` beyond the
   provisional `30/minute` default.

None of these can be resolved by more code — they require testing against a real Happ
install, which is explicitly out of scope until confirmed.
