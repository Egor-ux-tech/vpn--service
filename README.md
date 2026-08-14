# VPN Service

A commercial VPN service for users in Russia, controlled entirely through a Telegram bot:
WireGuard and VLESS+Reality under the hood, subscriptions and device management via chat,
an admin panel for operators, and a Smart VPN mode where users pick which services go
through the tunnel and which go direct.

No custom cryptography or VPN protocol — this is an orchestration layer around stock
WireGuard and stock Xray-core (VLESS+Reality).

## What's here

| Component | Stack | Role |
|---|---|---|
| `backend/` | Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic | Control plane: REST API, business logic, database |
| `bot/` | Python 3.12, python-telegram-bot | The primary user interface — everything a subscriber does happens in Telegram |
| `vpn/` | Python 3.12, FastAPI | Runs **on each WireGuard exit server**; the only thing that touches the real WireGuard interface |
| `xray-agent/` | Python 3.12, FastAPI | Runs **on each VLESS exit server**; the only thing that touches Xray-core's gRPC API — see docs/vless.md |
| `frontend/` | Next.js 16, TypeScript, Tailwind CSS | Staff-only admin panel |
| `infrastructure/` | Docker Compose, Ansible, GitHub Actions | Local dev stack, VPN server provisioning, CI/CD |

See [`docs/architecture.md`](docs/architecture.md) for why it's split this way (short
version: the bot is a thin client of the backend's API so business rules live in exactly
one place, and the vpn-agent is a separate deployable so a compromised exit server can't
touch billing data, and vice versa).

## Requirements

- Python 3.12+
- Node.js 22+ (admin panel only)
- Docker + Docker Compose (for local dev / running the control plane)
- PostgreSQL 16 (via Docker Compose, or your own instance)
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (for bot development)

## Local development

```
git clone <this-repo>
cd vpn-service
cp .env.example .env   # fill in a TELEGRAM_BOT_TOKEN at minimum; other change-me
                        # values are fine for local dev as-is
make up                 # backend + bot + postgres + redis
make migrate
make create-admin email=you@example.com
```

Each service also has its own local (non-Docker) workflow — useful for fast iteration:

```
cd backend    && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd bot        && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd vpn        && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd xray-agent && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd frontend && npm install
```

then `make backend-dev` / `make bot-dev` / `make frontend-dev` (each reads `.env` from the
repo root via each service's own `pydantic-settings`/`next.config.ts` config).

Run the test suites:

```
make test           # backend + bot + vpn + xray-agent, each in their own venv
make e2e-smoke       # cross-service: real backend + vpn-agent processes, full user journey
make lint            # ruff, all four Python services
make typecheck       # mypy, all four Python services
```

## Environment variables

See [`.env.example`](.env.example) for the full list with comments. The short version:
database/Redis URLs, `JWT_SECRET`/`ADMIN_SECRET`/`INTERNAL_SERVICE_TOKEN` (auth secrets),
`TELEGRAM_BOT_TOKEN`, `PAYMENT_PROVIDER` + its credentials, `VPN_AGENT_SHARED_SECRET` +
`VPN_DEFAULT_NETWORK`/`VPN_DNS`, and `XRAY_AGENT_SHARED_SECRET` (VLESS — deliberately a
separate secret from `VPN_AGENT_SHARED_SECRET`, see docs/vless.md). In production, the
backend/bot/vpn-agent/xray-agent all refuse to start if a secret is still at its
placeholder value — see [`docs/security.md`](docs/security.md).

## Database migrations

Schema changes go through Alembic, never hand-edited:

```
make migrate                         # apply
make makemigrations m="add foo"      # generate a new revision after changing app/models/*.py
```

## Running each service

- **Backend**: `make backend-dev` (or `uvicorn app.main:app --reload` from `backend/`) —
  API at `http://localhost:8000`, docs at `/docs`.
- **Bot**: `make bot-dev` (or `python -m app.main` from `bot/`) — starts Telegram polling
  plus an internal notify server on `:8801` (used by the backend to push messages like
  "your subscription expired").
- **Admin panel**: `make frontend-dev` — `http://localhost:3000`, login with the account
  from `make create-admin`.
- **Docker (everything)**: `make up` (core services) or `docker compose --profile frontend
  --profile monitoring up -d --build` (+ admin panel, + Prometheus/Grafana).

## VPN exit server setup / provisioning

VPN exit servers — both WireGuard and VLESS nodes — are provisioned separately from the
control plane, via Ansible (`infrastructure/ansible/site.yml` has one play per protocol,
targeting separate inventory host groups), since vpn-agent/xray-agent need direct access
to real host resources (a network interface, a loopback gRPC port) not sensible inside
the local dev Docker stack. See [`docs/wireguard.md`](docs/wireguard.md) /
[`docs/vless.md`](docs/vless.md) for the full picture and
[`docs/deployment.md`](docs/deployment.md) for the exact commands.

## Routing engine / Smart VPN

Split tunneling is implemented through WireGuard's own `AllowedIPs` — no custom protocol or
traffic inspection. A user picks `FULL VPN` or `SMART VPN`; in Smart VPN mode they choose
catalog categories (Video, Messengers, ...) and/or add their own domains, and the backend
resolves those into an aggregated CIDR list pushed to their device's config. Full details,
including how CDN/multi-IP domains and flaky DNS are handled, are in
[`docs/routing.md`](docs/routing.md).

## Payments

Provider-agnostic by design (`PaymentProvider` interface, MVP ships a safe local
`MockPaymentProvider` — never enable it for real money). A subscription only ever activates
from a signature-verified, idempotent webhook, never from the client-side "pay" action. See
`backend/app/services/payments/` and [`docs/security.md`](docs/security.md).

## Production deployment

See [`docs/deployment.md`](docs/deployment.md) — control plane via Docker Compose, VPN
servers via Ansible, the subscription-expiry sweep via a systemd timer, and what CI does
(and deliberately doesn't do — no automated prod deploy) on every push.

## Security

See [`docs/security.md`](docs/security.md) for the full picture: auth model, rate limiting,
audit logging, dependency vulnerability handling, and the service's privacy stance (no
browsing history, no traffic content ever stored).

## Troubleshooting

- **Backend won't start, complains about "insecure placeholder values"**: you set
  `ENVIRONMENT=production` with one or more secrets still at their `.env.example` default —
  this is intentional (see docs/security.md), replace them with real values.
- **Bot can't reach the backend**: check `BACKEND_API_BASE_URL` in the bot's environment and
  `INTERNAL_SERVICE_TOKEN` matches between bot and backend exactly.
- **Device provisioning fails with `vpn_agent_unreachable`**: the backend couldn't reach
  the vpn-agent for that device's server — check the server's `agent_base_url`, that the
  vpn-agent service is running (`systemctl status vpn-agent` on the exit server), and that
  `VPN_AGENT_SHARED_SECRET` matches between the backend and that specific agent.
  `docs/wireguard.md` covers the peer lifecycle if the agent is reachable but peers aren't
  behaving as expected.
- **VLESS device provisioning fails with `xray_agent_unreachable`**: same shape as above,
  but for the VLESS side — check `VLESSServerConfig.xray_agent_base_url`, that
  `xray-agent.service` is running on that node, and that `XRAY_AGENT_SHARED_SECRET`
  matches (it is deliberately a *different* secret from `VPN_AGENT_SHARED_SECRET`). See
  docs/xray-agent.md.
- **A payment webhook isn't activating a subscription**: check the webhook's `X-Signature`
  against `PAYMENT_WEBHOOK_SECRET`, and that the payment's `external_payment_id` actually
  matches a `Payment` row created by `POST /payments` — a webhook for an unknown payment
  returns 404 rather than silently failing.
- **Alembic autogenerate produces an empty migration**: run `alembic upgrade head` first —
  autogenerate diffs against the *current* DB state, not the previous migration file.
- **Tests failing only when run as the full suite, not individually**: check whether the
  test touches something process-global (the slowapi rate limiter is one example already
  handled — see the `app` fixture in `backend/tests/conftest.py` — since the FastAPI app is
  a session-wide singleton across the whole test run, not recreated per test).

## More documentation

- [`docs/architecture.md`](docs/architecture.md) — component boundaries and why
- [`docs/api.md`](docs/api.md) — REST API reference
- [`docs/deployment.md`](docs/deployment.md) — production deployment
- [`docs/security.md`](docs/security.md) — security and privacy
- [`docs/wireguard.md`](docs/wireguard.md) — WireGuard/vpn-agent internals
- [`docs/vless.md`](docs/vless.md) — VLESS+Reality internals (backend side)
- [`docs/xray-agent.md`](docs/xray-agent.md) — xray-agent service internals
- [`docs/routing.md`](docs/routing.md) — Smart VPN / routing engine internals
- [`tests/README.md`](tests/README.md) — cross-service integration test suite
