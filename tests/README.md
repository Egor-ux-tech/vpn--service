# Cross-service integration tests

Everything under `backend/tests`, `bot/tests`, and `vpn/tests` tests one service in
isolation (with the other two mocked or absent). This directory is different: it spins up
**real backend and vpn-agent processes** talking real HTTP to each other and drives them
through the bot's own `BackendClient`, to catch integration bugs that per-service mocks
structurally cannot — for example, a request/response contract mismatch between the
backend's `WireGuardProvider` and the real `vpn-agent` API, or a DB session dependency that
never actually commits (both real bugs this suite caught during development).

## Running

Requires the `backend` and `vpn` virtualenvs to already be set up (`pip install -e ".[dev]"`
in each — see their own READMEs). Run from the repo root:

```
make e2e-smoke
```

or directly:

```
cd backend && source .venv/bin/activate && pytest ../tests -v
```

The test spawns a real `uvicorn` process for the backend and one for the vpn-agent (using
each service's own venv interpreter), points the backend's `vpn_agent_shared_secret` and
`payment_webhook_secret` at fixed test values, runs Alembic migrations against a throwaway
SQLite file, and tears everything down afterward. `APPLY_TO_LIVE_INTERFACE=false` on the
vpn-agent means no real `wg`/`ip` commands run — this validates the HTTP contract and
business logic end-to-end, not actual WireGuard interface manipulation (that requires root
and a real network interface, out of scope for an automated test — see docs/wireguard.md).

## What it proves

The full "connect to VPN" user journey: Telegram auth → plan/server admin setup → payment
creation → webhook-confirmed subscription activation → device (peer) provisioning against a
live vpn-agent → peer status verified independently on the agent → disable → revoke. If this
passes, the three services' HTTP contracts and the core business flow are compatible right
now, not just individually mocked-correct.
