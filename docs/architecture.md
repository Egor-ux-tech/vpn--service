# Architecture

## 1. Overview

The service has five independently deployable components:

| Component  | Language/Framework                | Role                                                              |
|------------|------------------------------------|--------------------------------------------------------------------|
| `backend`  | Python 3.12 / FastAPI               | Control plane: REST API, business logic, database, orchestration   |
| `bot`      | Python 3.12 / python-telegram-bot   | User-facing Telegram UX, thin client of the backend API            |
| `vpn`      | Python 3.12 / FastAPI ("vpn-agent") | Data plane: runs **on each WireGuard server**, manages `wg` peers  |
| `frontend` | Next.js / TypeScript / Tailwind     | Admin panel (staff-only)                                           |
| `infrastructure` | Docker Compose / Ansible / GH Actions | Local dev environment, server provisioning, CI/CD            |

```
┌──────────────┐      HTTPS (JWT)      ┌───────────────────────────┐
│   frontend    │──────────────────────▶│         backend           │
│ (admin panel) │                       │  api / schemas / services │
└──────────────┘                       │  repositories / models    │
                                        │  core (config, security,  │
┌──────────────┐   HTTPS (bot token)    │        logging, errors)   │
│  Telegram API │◀────────────────────▶ │                            │
└──────┬───────┘                       └──────────┬─────────────────┘
       │                                            │
┌──────▼───────┐   HTTP (internal token)            │ Postgres / Redis
│      bot      │───────────────────────────────────┘
└──────────────┘

                                        backend ──HTTPS(HMAC)──▶ vpn-agent (per server)
                                                                    │ wg / ip / nft (root)
                                                                    ▼
                                                             WireGuard interface
```

The **bot never talks to the database directly** — it is a thin client of the backend's
internal HTTP API. This keeps a single source of truth for business rules (subscription
limits, device quotas, routing rules) and lets the admin panel, bot, and any future client
(mobile app, CLI) share the exact same logic.

The **vpn-agent never talks to Postgres** either. It is a small privileged service that
runs on VPN servers and only knows how to manage a WireGuard interface, nftables sets, and
report health/traffic stats. The backend is the only component that decides *what* the
desired peer state should be; the agent's job is to *reconcile* the WireGuard interface to
match.

This separation means a compromised or buggy VPN box cannot corrupt billing/user data, and
the control plane (backend, DB, bot) can run anywhere (e.g. a cheap EU VPS or serverless
container) independent of where VPN exit nodes are located.

## 2. Backend layering

```
app/api/v1/*        → FastAPI routers: parse request, call a service, return a schema.
                       No business logic, no direct DB/session queries here.
app/schemas/*        → Pydantic v2 models: request/response contracts.
app/services/*        → Business logic. Orchestrates repositories, enforces invariants
                       (device limits, subscription state machine, idempotent webhooks).
app/repositories/*    → Data access. One repository per aggregate, thin wrappers around
                       SQLAlchemy 2 (async) queries. No business rules here.
app/models/*          → SQLAlchemy ORM models (source of truth for schema, via Alembic).
app/core/*            → Config (pydantic-settings), DB session/engine, security (JWT,
                       password hashing), structured logging, error handling, DI wiring.
```

Dependency direction is strictly top-to-bottom: API → Schemas/Services → Repositories →
Models → Core. Services depend on repository *interfaces* (Protocols) so they can be unit
tested with fakes and so the VPN/payment providers can be swapped later.

## 3. VPN provisioning abstraction

```python
class VPNProvider(Protocol):
    async def create_peer(self, device: Device, server: VPNServer) -> PeerProvisioningResult: ...
    async def delete_peer(self, peer: VPNPeer) -> None: ...
    async def disable_peer(self, peer: VPNPeer) -> None: ...
    async def enable_peer(self, peer: VPNPeer) -> None: ...
    async def get_peer_status(self, peer: VPNPeer) -> PeerStatus: ...
    async def build_client_config(self, peer: VPNPeer, allowed_ips: list[str]) -> str: ...
```

`WireGuardProvider` is the MVP implementation: it calls the **vpn-agent** REST API running
on the target `VPNServer` over HTTPS, authenticated with an HMAC-signed request using a
per-server shared secret (`VPN_AGENT_SHARED_SECRET`). The agent generates the WireGuard
keypair **on the server**, returns the private key exactly once in the provisioning
response, and never persists or logs it. The backend forwards the private key straight
through to the bot (over the already-encrypted Telegram Bot API channel) and does **not**
store it — only the public key and assigned IP are persisted in `vpn_peers`/`devices`.
This bounds the blast radius of a leaked database to public keys and metadata only.

Because provisioning goes through an interface, a future `AmneziaWGProvider`,
`OpenVPNProvider`, or `MultiHopProvider` can be added without touching backend business
logic, API contracts, or the bot.

## 4. Smart Routing (Split Tunneling)

WireGuard's own `AllowedIPs` mechanism is used for split tunneling — no custom protocol or
traffic-inspection component is built. Two profile modes exist:

- **FULL VPN**: peer's `AllowedIPs` = `0.0.0.0/0, ::/0` (all traffic tunneled).
- **SMART VPN**: `AllowedIPs` = the union of IP ranges resolved from the domains attached to
  the user's enabled `routing_categories` / `routing_rules`, plus any custom domains they add.

The **routing engine** (`app/services/routing`) periodically (and on-demand when a user
edits their whitelist) resolves each active domain's A/AAAA records, unions the results
into CIDR blocks per routing profile, and regenerates the peer's `AllowedIPs` snapshot.
Because CDNs rotate IPs and one domain can have many records, the engine:

- always resolves fresh, keeps the **previous** resolution as a fallback if a lookup fails
  (never drops a domain to empty on a transient DNS error);
- stores multiple IPs per domain, not one;
- supports IPv4 and IPv6 independently;
- de-duplicates/aggregates overlapping ranges before writing the profile;
- is versioned — each `vpn_profiles` row is a snapshot, so an old profile is never mutated
  in place while a client might be reading it.

The user's **own device DNS is left untouched** for DIRECT domains — only VPN-bound traffic
uses the pushed `VPN_DNS` resolvers, which limits DNS-leak exposure for the traffic that is
supposed to be private, while non-VPN domains resolve exactly as they would without the
service running.

## 5. Data model

See [`docs/api.md`](api.md) for the endpoint surface and the SQLAlchemy models under
`backend/app/models/` for the authoritative schema (managed via Alembic migrations, never
hand-edited in production).

## 6. Trust boundaries / privacy

- The backend stores **metadata required to operate the service** (which server a device is
  on, its assigned IP, subscription state, which routing *categories* are enabled) — it does
  **not** log or store the content of user traffic, nor a history of visited sites. Routing
  rules describe "this category goes via VPN," not "user visited X at time Y."
- Private keys exist in memory only for the duration of a single provisioning request/response
  and are never written to logs or the database.
- See [`docs/security.md`](security.md) for the full threat model and hardening checklist.

## 7. Why these boundaries

- **Bot as thin client** — keeps exactly one implementation of "can this user add a 6th
  device," reachable and testable via the same HTTP API used by the admin panel.
- **vpn-agent as a separate deployable** — lets VPN exit servers be provisioned, rotated, or
  geographically distributed independently of the control plane, and confines root/privileged
  system calls (`wg`, `ip`, `nft`) to a single small, auditable codebase.
- **Provider interfaces for VPN and payments** — MVP ships WireGuard + a mock/manual payment
  provider, but the interfaces exist so a second VPN transport or a real payment gateway
  (YooKassa, Cryptomus, Stripe) is a new adapter, not a rewrite.
