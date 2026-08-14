# Deployment

The service has two deployment targets that are provisioned differently:

- **Control plane** (backend, bot, frontend, Postgres, Redis, Prometheus, Grafana) — runs
  as Docker containers, typically on a single small VPS or a container platform.
- **VPN exit servers** — two independent flavors, both provisioned with Ansible, running
  natively (not in Docker):
  - **WireGuard nodes** (WireGuard + vpn-agent + node_exporter), needing direct access
    to the host's network namespace to manage a real `wg0` interface. See docs/wireguard.md.
  - **VLESS nodes** (Xray-core + xray-agent + node_exporter). See docs/vless.md and
    docs/xray-agent.md.

These are independent: you can run one control plane against any number of exit servers in
different countries, added/removed without touching the control plane's deployment.

## Prerequisites

- A Linux host (Ubuntu 22.04+ recommended) for the control plane, with Docker + Docker
  Compose installed.
- One Linux host per VPN exit server, reachable over SSH, with a public IP.
- A Telegram bot token (from [@BotFather](https://t.me/BotFather)).
- Two domains (or subdomains) pointed at the control-plane host's public IP — one for the
  backend API, one for the admin panel — for the production compose file's automatic-HTTPS
  reverse proxy (see "TLS / reverse proxy" below). Not required for local dev (`make up`),
  which talks to `backend:8000`/`frontend:3000` directly over plain HTTP.

## Control plane

```
git clone <this-repo>
cd vpn-service
cp .env.example .env
# Edit .env: set ENVIRONMENT=production and replace every change-me* value with a real
# secret (openssl rand -hex 32 is a reasonable way to generate them). The backend refuses
# to start in production with any placeholder left in place — see docs/security.md.

docker compose up -d --build backend bot postgres redis
docker compose exec backend alembic upgrade head
```

Create the first admin account (prefer this over the HTTP bootstrap endpoint when you have
shell access — see docs/security.md):

```
make create-admin email=you@example.com
```

Start the admin panel (separate profile, since it's optional for a bot-only deployment):

```
docker compose --profile frontend up -d --build frontend
```

Start monitoring (optional, separate profile):

```
make up-monitoring
# Prometheus: http://<host>:9090   Grafana: http://<host>:3001 (admin / GRAFANA_ADMIN_PASSWORD)
```

The steps above (`docker-compose.yml`) publish the backend and admin panel directly on the
host — fine for local development or a staging box reached over SSH tunnel/VPN, but the
backend and frontend are then reachable by anyone who can reach that port, over plain HTTP.
For anything reachable from the public internet, use the TLS-terminated production stack
instead of the steps above.

### TLS / reverse proxy (production)

`docker-compose.prod.yml` is a separate, self-contained compose file (not an overlay — see
the comment at its top for why) that puts [Caddy](https://caddyserver.com/) in front of the
backend and admin panel with automatic HTTPS, and removes their host port bindings
entirely — in this stack, **Caddy is the only container reachable from outside the host**.
Caddy obtains and renews Let's Encrypt certificates itself; there's nothing to run
`certbot` for.

**Before starting it:**

1. Point two DNS records at the host's public IP — one for the API, one for the admin
   panel (an A record, and an AAAA record too if the host has a public IPv6 address; see
   docs/security.md's IPv6 section for why leaving AAAA dangling or absent-but-listening is
   worth checking either way). These must already resolve — Caddy requests the certificate
   the first time it sees traffic for each domain, and the ACME HTTP-01 challenge fails if
   the domain doesn't point here yet.
2. Ensure ports 80 and 443 are open to the internet on this host (security group / cloud
   firewall, and `ufw`/`nftables` if enabled locally). Port 80 is required even though the
   site is HTTPS-only — it's used for the ACME challenge and to redirect to HTTPS.
3. In `.env`, set `API_DOMAIN`, `ADMIN_DOMAIN` (the two real domains from step 1),
   `ACME_EMAIL` (a real, monitored address — Let's Encrypt uses it for expiry/revocation
   notices, not for anything user-facing), and `NEXT_PUBLIC_API_BASE_URL` to
   `https://<API_DOMAIN>`. Also set `BACKEND_CORS_ORIGINS` to `["https://<ADMIN_DOMAIN>"]`
   so the backend accepts browser requests from the real admin panel origin.

```
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
docker compose -f docker-compose.prod.yml exec backend python -m app.scripts.create_admin --email you@example.com
```

Watch the first startup for certificate issuance:

```
docker compose -f docker-compose.prod.yml logs -f caddy
```

If a domain doesn't resolve yet, or 80/443 aren't reachable, Caddy logs the ACME failure
and keeps retrying — it does not fall back to serving plaintext HTTP or a self-signed
certificate, so a misconfigured domain fails loudly rather than silently downgrading.

### Subscription expiry

Not a long-running worker — it's a sweep meant to run periodically. Add a systemd timer (or
cron) on the control-plane host:

```ini
# /etc/systemd/system/vpn-expiry.service
[Unit]
Description=VPN subscription expiry sweep

[Service]
Type=oneshot
WorkingDirectory=/path/to/vpn-service
ExecStart=/usr/bin/docker compose exec -T backend python -m app.workers.run_expiry_worker
```

```ini
# /etc/systemd/system/vpn-expiry.timer
[Unit]
Description=Run the VPN subscription expiry sweep hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```
systemctl enable --now vpn-expiry.timer
```

## VPN exit servers

`infrastructure/ansible/site.yml` has **two independent plays** — one per host group, so
a single inventory can provision both WireGuard and VLESS nodes (or just one kind):

```
cd infrastructure/ansible
cp inventory/hosts.ini.example inventory/hosts.ini      # real hosts, both [vpn_servers]
                                                          # and [vless_servers] groups
cp group_vars/all.yml.example group_vars/all.yml        # real secrets — must match the
                                                          # control plane's
                                                          # VPN_AGENT_SHARED_SECRET AND
                                                          # XRAY_AGENT_SHARED_SECRET
ansible-playbook -i inventory/hosts.ini site.yml
```

**WireGuard nodes** (`[vpn_servers]`) — see docs/wireguard.md. After the run completes,
register each server via the admin panel (Servers page) or `POST /api/v1/servers`, using
the public key the playbook printed, then flip its status to `online`.

**VLESS nodes** (`[vless_servers]`) — see docs/vless.md and docs/xray-agent.md. After the
run completes, register each node via `POST /api/v1/vless-servers` using the **Reality
public key** the playbook printed (never the private key, which never leaves the node),
then flip its status to `online`.

A server that isn't `online` (of either protocol) is never selected for new device
provisioning.

Add each new exit server's metrics endpoints — `vpn-agent:8800/metrics` or
`xray-agent:8801/metrics`, plus `:9100` (node_exporter) on both — to
`infrastructure/monitoring/prometheus/prometheus.yml`'s scrape jobs and reload/restart the
`prometheus` container.

## CI/CD

GitHub Actions (`.github/workflows/`) runs, per service (backend, bot, vpn-agent,
xray-agent, frontend), on every push/PR that touches it: dependency install → Ruff →
mypy → pytest (+ coverage) → `pip-audit`/`npm audit` → a Docker build of that service's
image. `e2e.yml` additionally runs the cross-service smoke test
(`tests/`, see its own README) whenever backend, vpn-agent, bot, or the shared tests change.
`security.yml` scans every push/PR for committed secrets (gitleaks). `backend.yml` also runs
a dedicated `postgres` job against a real `postgres:16-alpine` service container — see
"PostgreSQL compatibility" below; everything else in that workflow runs on SQLite for speed.

### PostgreSQL compatibility

The main backend test suite runs on SQLite (fast, no service dependency) and cannot catch
Postgres-specific issues — most importantly, whether an Alembic migration written and
tested against SQLite (e.g. one using `batch_alter_table` to work around SQLite's lack of
ALTER-based constraint support) actually produces the intended schema on Postgres, and
whether transaction/SAVEPOINT-dependent code (like the IP-allocation race fix in
`DeviceService._create_peer_with_retry`) behaves the same under Postgres's real locking.
Production only ever runs Postgres (see `docker-compose.yml`), so `tests/postgres/` closes
that gap: migrations against a genuinely empty database (drops and recreates the `public`
schema first), a downgrade/upgrade round trip, a direct check that the unique constraint
from the IP-allocation fix exists in Postgres's own catalogs, and transaction/rollback/
SAVEPOINT behavior exercised through the real `DeviceService` code path. It's skipped
automatically (not run against SQLite as a substitute) unless `POSTGRES_TEST_DATABASE_URL`
is set — CI always sets it; to run locally:

```
docker compose up -d postgres
cd backend
POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://vpnservice:change-me@localhost:5432/vpnservice \
    python -m pytest tests/postgres -v
```

**There is no automated production deploy step by design** — promoting a build to
production is a deliberate, manual action until a deployment target and rollback strategy
are chosen. A straightforward next step once you have one: build and push images in CI,
then `docker compose pull && docker compose up -d` on the control-plane host (or the
equivalent for your target platform), triggered manually or via a separate, explicitly
authorized workflow.

## Backups

- **Postgres**: back up the `postgres-data` volume (or use your platform's managed Postgres
  backup feature — nothing in this repo assumes a specific backup mechanism).
- **WireGuard server keys** (`/etc/wireguard/privatekey` on each exit server): losing this
  means re-provisioning that server and re-registering its (new) public key — existing
  peers on that server would need to reissue their device configs. Not catastrophic, but
  worth including in your server backup/snapshot policy if you want to avoid it.
- **vpn-agent's `state.db`**: rebuildable from the backend's own `vpn_peers` table (the
  backend is the source of truth for *desired* peer state — see docs/architecture.md) —
  not essential to back up separately, but losing it means peers won't reconcile until the
  backend re-pushes them (e.g. via a manual re-provisioning pass), so treat this as a minor
  operational inconvenience, not a data-loss risk.
- **Reality private key** (`/etc/xray/reality_private_key` on each VLESS node): losing
  this means re-provisioning that node and re-registering its (new) public key — every
  existing VLESS user on that node would need a fresh subscription-link fetch to pick up
  the new key (no reissue step required, since the subscription link is live-fetched —
  see docs/vless.md). Worth including in your server backup/snapshot policy if you want to
  avoid the disruption.
- **xray-agent's `state.db`**: same story as vpn-agent's — rebuildable from the backend's
  `vless_credentials` table, not essential to back up separately.

## Scaling notes (beyond MVP)

- Multiple backend replicas behind a load balancer work as-is — it's stateless aside from
  the DB/Redis, both externalized.
- The bot currently runs Telegram polling (`run_polling`), which only supports a single
  instance; moving to webhook mode is the natural next step for horizontal bot scaling.
- The subscription-expiry sweep is safe to run more than once concurrently (each expired
  subscription is only ever transitioned out of `ACTIVE` once — a second sweep run against
  an already-expired subscription simply finds nothing left to do), so no distributed lock
  is required even with multiple control-plane hosts each running the timer.
