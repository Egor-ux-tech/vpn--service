# Production Readiness Audit

**Date of audit:** 2026-08-13
**Date of fix pass:** 2026-08-14 (this update)
**Method (audit):** Fresh re-run of every automated test/lint/type-check suite in this
sandbox, plus direct code/config inspection (grep, manual reading) looking specifically for
gaps that passing tests would not reveal.
**Method (fix pass):** Implemented the 8 critical fixes below, each verified with new tests
that exercise the actual behavior being fixed (not just "the code runs"), then re-ran every
test/lint/type-check suite. Two real, previously-unknown bugs were found *while writing
those verification tests* and fixed in the same pass — see "New findings from the fix
pass" below. This section is a status update, not a rewrite: the original audit findings
below are left in place with their resolution noted inline, so the history of what was
found and when stays legible.

**Headline finding, stated up front (2026-08-13, still true 2026-08-14):** every automated
check in this repository passes — as of the fix pass, 131 tests execute and pass across all
services (72 backend + 8 gracefully skipped Postgres-only tests + 30 vpn-agent + 28 bot + 1
cross-service E2E) plus a clean frontend build/lint/typecheck — and that is a real,
meaningful signal — but **no code in this repository has ever touched a real Linux VPS, a
real WireGuard kernel interface, a real Postgres instance, a real Docker daemon, a real
payment provider, or a real Telegram bot token.** This sandbox is macOS with no `docker`,
no `wg`/`nft` binaries, no `/dev/net/tun`, no local PostgreSQL, and the repository still has
**no history of a real CI run** (GitHub Actions has never executed against this code on
real infrastructure). Every "PASS" below means "the code does what the code believes
reality looks like" — not "this has been proven against reality." Treat this document as
the list of what still needs to happen before that gap closes.

**What the fix pass actually closed**: the 8 items were chosen because they were the
findings most likely to cause a *real incident* on first production use (silent data
corruption, an outage-causing single point of failure, a security-relevant leak, or
plaintext credentials in transit) — not because they were the only remaining gaps. The
"still needs a real VPS" gap described above is unchanged by this pass; see "Remaining
blockers for first real deployment" at the end of this document for the concrete list.

## Status table

Rows touched by the 2026-08-14 fix pass carry a `[FIXED 08-14]` marker in the Status
column; the rest are unchanged from the original 2026-08-13 audit.

| # | Component | Status | Tested real | Remaining work | Risk |
|---|---|---|---|---|---|
| 1 | Backend (FastAPI) | PARTIALLY READY `[IMPROVED 08-14]` | HTTP contract, business logic, DB commit/rollback (SQLite) — 72 tests + live E2E over real HTTP; migrations/transactions/constraint now also structurally verified against a real-Postgres test package (`tests/postgres/`, gated on a reachable Postgres — 8 tests, currently skipped in this sandbox, wired into CI against a real `postgres:16-alpine` service container) | Actually run `tests/postgres/` once against a live Postgres outside this sandbox (CI will do this on first push); load/concurrency test at real traffic levels; TLS termination (see #7, now fixed) | LOW–MEDIUM |
| 2 | vpn-agent | NOT READY | HTTP contract, HMAC auth, peer-store logic, `wg` command construction (fake runner) — 30 tests | Real `wg`/`wg-quick`/`nft` execution on a real host; real interface up/down; real restart with on-disk state (tests only ever used `:memory:`) | **HIGH** |
| 3 | Telegram bot | PARTIALLY READY | Handler logic, backend HTTP contract — 28 tests, all with a fake Telegram Bot API | Real bot token, real Telegram servers, real message/QR/document delivery, real user interaction | MEDIUM |
| 4 | Admin panel | PARTIALLY READY `[IMPROVED 08-14]` | tsc/eslint/build clean; one live smoke test (curl-level) of the login redirect flow against a real running Next.js + backend | Real browser click-through (no Playwright/Cypress exists); the dead `refresh_token` field is gone (see finding #4 below — removed, not implemented) so there's no false impression of session refresh; admins are still logged out after 30 min with no silent renewal, which is now the *documented*, intentional behavior rather than a half-built feature | LOW |
| 5 | WireGuard configuration | **BLOCKED** | Nothing — `ansible-playbook --syntax-check`/`--list-tasks` only. IPv6 forwarding/nftables hardening (see IPv4/IPv6 finding below) verified via 4 plain-text config-assertion tests, not a real `nft`/sysctl run | A real Linux host to run the playbook against at all | **HIGH** |
| 6 | Smart VPN / routing | PARTIALLY READY `[IMPROVED 08-14]` | Aggregation/fallback logic against a **fake** DNS resolver — 4 tests; the full `RoutingService.regenerate_profile` code path (not just the aggregation helper) is now also tested end-to-end for both full-tunnel and split-tunnel modes, including real dual-stack (IPv4+IPv6) domain resolution — 3 new tests | Real DNS resolution (dnspython against real nameservers) never exercised; a real WireGuard client's actual split-tunnel behavior with a generated config never observed | MEDIUM–HIGH |
| 7 | Authentication & authorization | PARTIALLY READY `[IMPROVED 08-14]` | JWT/bcrypt/RBAC/rate-limit logic thoroughly tested, incl. a real caught-and-fixed DB commit bug. Production TLS termination is now provided (Caddy, automatic HTTPS via Let's Encrypt — `docker-compose.prod.yml` + `infrastructure/caddy/Caddyfile`), and the dead `refresh_token` mechanism is removed (see finding #4) | Caddy config has not been run against a real domain/DNS (needs a real VPS + real DNS records — see docs/deployment.md's "TLS / reverse proxy" section for the exact checklist); rate limiting is now Redis-backed and distributed (see finding #1) but has likewise never run against a real multi-replica deployment | LOW–MEDIUM |
| 8 | Payment abstraction | **NOT READY** for real money | Mock provider + webhook idempotency/signature verification — but only against the mock's *own* self-consistent signing scheme | Every real provider (YooKassa/Cryptomus/Stripe/...) is **unimplemented** — `NotImplementedError` today. Real providers' actual webhook payload shape and signature scheme are unverified against this interface | **HIGH** |
| 9 | Subscription expiry | READY (logic) / PARTIALLY READY (ops) | Worker logic tested with explicit past `expires_at` values | Never fired by an actual elapsed wall-clock wait or a real cron/systemd timer | LOW–MEDIUM |
| 10 | Secrets handling | READY (design) / UNVALIDATED (practice) `[IMPROVED 08-14]` | Production-placeholder guard is unit-tested and works; secret-redaction logic now has direct tests in all 3 services (see finding #7 below) | gitleaks has never scanned a real commit; dead `NEXTAUTH_*` env vars removed (see finding #6 below — fixed, not just flagged) | LOW |
| 11 | Docker configuration | **NOT TESTED AT ALL** | Nothing — `docker` is not installed in this sandbox (still true 08-14) | `docker build`/`docker compose up` has never run, not once, for any of the 4 app images (backend, bot, vpn-agent, frontend) or the new `docker-compose.prod.yml` stack (those 4 plus the stock `caddy:2-alpine` image); the compose files are only known to be YAML-valid, never actually brought up | **HIGH** |
| 12 | Ansible deployment | NOT TESTED AGAINST A REAL HOST | `--syntax-check`, `--list-tasks` only | Real run (or at least `--check`) against a real target; `node_exporter` role's hardcoded download version/URL never verified reachable; the IPv6-hardening change to `roles/wireguard/tasks/main.yml`/`nftables.conf.j2` (see below) is new and specifically untested against a real `nft` binary | **HIGH** |
| 13 | GitHub Actions | **NEVER EXECUTED** `[CHANGED 08-14]` | YAML validated locally only | First real push will be the first real run. `backend.yml` gained a new `postgres` job (real `postgres:16-alpine` service container) that has literally never executed, since there is no CI run yet — its correctness is inferred from local reasoning about GitHub Actions' `services:` syntax, not observed | MEDIUM–HIGH |
| 14 | Monitoring | PARTIALLY READY | `/metrics` on backend/vpn-agent/bot verified live via curl, real Prometheus text format | Prometheus/Grafana configs are schema-valid JSON/YAML only — never loaded into a running Prometheus/Grafana; `vpn-agent`/`node` scrape targets are empty placeholders until real servers exist | LOW–MEDIUM |
| 15 | Logging | READY `[FIXED 08-14]` | Consistent structured logging across all 3 services; `_redact_sensitive` now has direct tests in all 3 services proving every listed key is actually scrubbed (case-insensitively), and that non-sensitive keys pass through unchanged | None outstanding for the redaction mechanism itself | LOW |
| 16 | Database migrations | READY (SQLite) / STRUCTURALLY VERIFIED (Postgres) `[IMPROVED 08-14]` | Generated, applied, re-verified zero-drift against SQLite; a new `tests/postgres/` package runs the real `alembic upgrade head`/`downgrade` commands against a real, freshly-emptied Postgres database, verifies the resulting schema and the Fix-1 unique constraint via `pg_constraint`, and exercises real transaction/SAVEPOINT behavior — all gated on `POSTGRES_TEST_DATABASE_URL` and **not executed in this sandbox** (no Postgres available here); wired into CI to run for real on every push | Confirm the CI `postgres` job actually goes green on first real push (see #13); `native_enum=False` and JSON-column behavior under asyncpg remain otherwise unverified beyond what the new package covers | LOW–MEDIUM |
| 17 | Backup/recovery | **NOT IMPLEMENTED** | N/A | Docs describe what to back up; no backup script, no restore drill has ever been performed | MEDIUM–HIGH |
| 18 | Security | PARTIALLY READY `[IMPROVED 08-14]` | Real CVEs found and fixed pre-08-14 (starlette, python-jose→ecdsa) via `pip-audit`, verified with the full test suite before/after; `pip-audit` re-run clean (no known vulnerabilities) across all 3 Python services and `npm audit` clean on the frontend as part of this fix pass | See "New findings from this audit" below — items 1, 3, 5, 6, 7 fixed; item 2 fixed (Redis now used); item 4 fixed (removed). See also "New findings from the fix pass" for two additional bugs found and fixed while implementing these | LOW–MEDIUM |
| 19 | Error handling | READY `[FIXED 08-14]` | 404/401/403/409/422 all tested; the generic unhandled-exception → 500 handler now has direct tests (proving the response body never leaks exception internals, and carries a usable `request_id`) — writing that test surfaced and fixed a real bug, see "New findings from the fix pass" | None outstanding for the handler itself | LOW |
| 20 | Documentation | READY `[FIXED 08-14]` | `docs/deployment.md`'s "Scaling notes" claim that multiple backend replicas "work as-is" is now actually true for rate limiting (Redis-backed, see finding #1) — corrected in place rather than just flagged; `docs/wireguard.md` gained a full "IPv6 strategy" section; `docs/deployment.md` gained a "TLS / reverse proxy" section and a "PostgreSQL compatibility" section | None outstanding | LOW |

## New findings from this audit (2026-08-13; resolution status as of 2026-08-14)

These were found by actively looking for gaps, not by re-reading what was already written
down as done. None were caught by any passing test at the time they were found.

1. ✅ **FIXED.** Rate limiter was in-memory, not distributed, despite Redis being
   provisioned. `backend/app/core/rate_limit.py` now passes `storage_uri=settings.redis_url`
   to `Limiter(...)`, backed by `limits`' `RedisStorage` (a real Lua `EVALSHA`
   increment-and-expire, so concurrent replicas can't race each other on the same counter).
   Proven with two new tests: one confirms the shared app limiter actually uses
   `RedisStorage` not the in-memory default, the other constructs two independent `Limiter`
   instances (simulating two backend replicas) and shows a hit recorded by one counts
   against the other's view of the same key. **Also required, and easy to miss**:
   `in_memory_fallback_enabled=True` + `swallow_errors=True` — see "New findings from the
   fix pass" below for why the naive Redis-only config would have been worse than the
   original bug.

2. ✅ **FIXED** (as a consequence of #1). Redis is no longer unused — it now backs the
   distributed rate limiter, the only real use the stack currently has for it.

3. ✅ **FIXED.** IP allocation's check-then-act race is closed with a real database-level
   unique constraint on `(vpn_peers.server_id, vpn_peers.assigned_ip)`
   (migration `3073258ed68f`), and `DeviceService._create_peer_with_retry` now catches the
   resulting `IntegrityError`, cleans up the orphaned agent-side peer, and retries with a
   freshly rescanned IP (bounded at 5 attempts, then a clear `ConflictError`). Proven three
   ways: a deterministically engineered collision, a proof that repeated collisions
   eventually surface a clean error instead of hanging, and a *genuinely concurrent*
   HTTP-level test (6 simultaneous `POST /devices` requests via `asyncio.gather` against
   real, separate database connections — file-based SQLite with a real connection pool, not
   the suite's usual `:memory:` + `StaticPool`, which was verified NOT to exhibit real
   cross-connection transaction isolation and would have made this test meaningless).

4. ✅ **FIXED — removed, not implemented.** The dead `refresh_token` mechanism (issued by
   `/auth/admin/login`/`/auth/admin/bootstrap`, consumed by nothing, not even stored by the
   frontend) is gone: `AdminTokenResponse` no longer has the field, `TokenType` has only
   `ACCESS`, and `jwt_refresh_token_expire_days` is removed from settings/`.env.example`.
   Chosen over implementing real rotation/revocation because nothing in the product actually
   needed silent session renewal — building that machinery would have been a new feature,
   not a fix. Admins still re-authenticate every `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (30 min);
   that's now documented, intentional behavior instead of a half-built one.

5. ✅ **FIXED.** Production TLS/reverse-proxy infrastructure now exists:
   `docker-compose.prod.yml` (standalone, not an overlay — see its header comment for why)
   puts Caddy in front of the backend and admin panel with automatic HTTPS, and neither is
   published to the host at all in that file — Caddy is the only internet-facing container.
   `infrastructure/caddy/Caddyfile` has no real domains/secrets baked in (env-var
   placeholders only). `docs/deployment.md` documents the exact DNS/port/cert prerequisites.
   Not yet run against a real domain (see #13/#5 in the status table).

6. ✅ **FIXED.** Dead `NEXTAUTH_SECRET`/`NEXTAUTH_URL` removed from `.env.example` and
   `docker-compose.yml`'s frontend service — confirmed via full-repo grep that nothing
   referenced them (the admin panel's auth is the backend's own JWT, not NextAuth.js).

7. ✅ **FIXED.** `_redact_sensitive` now has direct tests in all three services
   (`backend/tests/unit/test_logging_redaction.py`, `bot/tests/test_logging_redaction.py`,
   `vpn/tests/test_logging_redaction.py`), each asserting every key in that service's own
   `_REDACT_KEYS` set is actually scrubbed (case-insensitively) and non-sensitive keys pass
   through untouched. Also documented as a boundary, not silently assumed: redaction is
   key-based, not a scan of value contents — a secret embedded in an unrelated field's value
   (e.g. inside a free-text exception message) is not caught by this mechanism, by design.

## New findings from the fix pass (2026-08-14, found while implementing the above)

Neither of these was in the original audit — both were caught by the process of writing a
*real* verification test for one of the 8 requested fixes, not by inspection. Consistent
with this document's whole premise: tests that exercise real behavior find things code
review doesn't.

1. **Naively pointing the rate limiter at Redis would have turned a Redis blip into a full
   API outage — worse than the bug it fixed.** Discovered when the cross-service E2E suite
   (`tests/test_full_stack_e2e.py`), which has no Redis available, started failing after
   switching to Redis-backed rate limiting. With `storage_uri` set and no further config,
   *every* request — including `/health` — 500s the instant Redis is unreachable, because
   slowapi lets the storage backend's `ConnectionError` propagate. Worse: `swallow_errors=True`
   alone does not fix this — it has its own bug where the swallowed check still crashes the
   *response* path afterward (it tries to read `request.state.view_rate_limit` for header
   injection, which was never set because the check never completed). The actual fix needed
   both `in_memory_fallback_enabled=True` (degrades to a real, working per-process limiter —
   the pre-fix behavior — the moment Redis throws, and auto-recovers once Redis is reachable
   again) *and* `swallow_errors=True` as a last-resort backstop. Verified with a dedicated
   test that points a `Limiter` at an unreachable Redis (a real refused TCP connection, not
   a mock) and proves a request still succeeds. **Take-away for whoever deploys this**: if
   Redis and the backend both go down together, or Redis is misconfigured at first boot,
   the backend degrades to un-distributed rate limiting rather than refusing all traffic —
   confirm this is the desired failure mode.

2. **The generic 500 handler's `request_id` field was always `"-"` (the unset sentinel),
   not the real request ID — defeating support correlation for exactly the errors where it
   matters most.** Root cause: FastAPI/Starlette always wraps the entire app in
   `ServerErrorMiddleware` *outside* every `add_middleware()`-registered middleware
   (including `RequestContextMiddleware`, which sets the request-ID contextvar) —
   confirmed by reading `Starlette.build_middleware_stack`. By the time an unhandled
   exception reaches `ServerErrorMiddleware` and it calls the registered `Exception`
   handler, `RequestContextMiddleware`'s own `finally` block has already reset the
   contextvar back to `"-"` while the exception was unwinding through it. `AppError`/
   `RequestValidationError`/`HTTPException` responses were unaffected (handled by
   `ExceptionMiddleware`, which sits *inside* `RequestContextMiddleware`) — only genuine,
   unhandled 500s were broken. **Fix**: `RequestContextMiddleware` now also stashes the
   request ID on `request.state.request_id` (a plain attribute on the same `Request` object
   the 500 handler receives, unaffected by the contextvar-reset timing issue), and
   `app/core/errors.py` reads from there first. Caught by
   `tests/integration/test_error_handlers.py`, which also had to work around an unrelated,
   separate quirk to test this at all: httpx's `ASGITransport` by default re-raises the
   original exception into the test after Starlette sends the response — intentional
   Starlette behavior (the response is sent to the client, then the exception is re-raised
   so the process-level ASGI runner, e.g. uvicorn, still logs it) that a real HTTP client
   never observes, since it only sees response bytes. The test uses
   `ASGITransport(raise_app_exceptions=False)` to match what a real client actually sees.

## The "pay special attention to" list, addressed directly

- **Real WireGuard traffic**: never observed. `APPLY_TO_LIVE_INTERFACE=false` in every test
  and in the E2E suite; this sandbox has no `wg` binary and no `/dev/net/tun` at all —
  categorically impossible to exercise here.
- **NAT/firewall (nftables)**: template written (`roles/wireguard/templates/nftables.conf.j2`),
  never applied — no `nft` binary available to even syntax-check the ruleset locally, let
  alone confirm it actually masquerades/forwards traffic correctly. `[UPDATED 08-14]` the
  template gained explicit IPv6-drop rules in the `forward` chain and a comment clarifying
  the `ip nat` table is deliberately IPv4-only — same "never run against real `nft`" caveat
  applies to this new content as to the rest of the file.
- **DNS**: the Smart VPN resolver has real dnspython code behind it, but every test feeds
  it a fake, in-memory resolver. Real-world DNS behavior (timeouts, SERVFAIL, actual CDN
  record sets) is unverified.
- **IPv4/IPv6**: `[RESOLVED — was a real, if latent, gap]` audited end to end and
  explicitly documented in `docs/wireguard.md`'s new "IPv6 strategy" section: this service
  is IPv4-only by deliberate design, not by accident. Client configs route `::/0` into the
  tunnel specifically so a dual-stack client's IPv6 traffic doesn't silently bypass the VPN
  via the OS's normal path (verified: `RoutingEngine.full_vpn_allowed_ips()` and
  `RoutingService.regenerate_profile`'s full-tunnel default both include it, now tested
  end-to-end, not just at the aggregation-helper level). On the exit-server side, a real gap
  *was* found and fixed: `net.ipv6.conf.all.forwarding` was enabled in the Ansible sysctl
  task even though nothing in this stack forwards or NATs IPv6 — now disabled, with an
  explicit nftables drop rule added as defense in depth on top of WireGuard's own
  cryptokey routing (server-side peer `AllowedIPs` is always IPv4-only, so a stray IPv6
  packet would be rejected at that layer regardless). Smart VPN's domain-resolution path
  already handled AAAA records symmetrically with A records (pre-existing, now additionally
  covered by an end-to-end test) — the gap was specifically at the exit-server network
  layer, not in the routing logic. `ip_allocator.py`'s actual peer-IP allocation is still
  **only ever exercised for IPv4** in practice (no `VPNServer.internal_network` is ever
  configured as an IPv6 CIDR) — this is consistent with the documented IPv4-only strategy,
  not a remaining gap.
- **Smart VPN routing**: logic-correct against synthetic data; never validated that a real
  WireGuard client actually honors a generated `AllowedIPs` list the way the design assumes.
- **Reconnect behavior**: untested — no real client exists to reconnect.
- **Server restart**: `PeerReconciler.reconcile_on_startup` is logically sound and
  unit-tested against the SQLite peer store, but never exercised against a real `wg0`
  interface actually coming back up correctly after a reboot.
- **vpn-agent restart**: state persistence (`STATE_DB_PATH`) is `:memory:` in 100% of test
  runs — the on-disk SQLite path a real deployment would use has never been exercised, so
  "does state survive an agent restart" is unverified.
- **Expired subscriptions**: logic tested with fabricated past timestamps; never fired by an
  actual timer in real time.
- **Concurrent users**: no general load testing exists (still a gap). The one concrete
  concurrency bug this audit found (IP allocation race, finding #3) is fixed and now proven
  under genuine concurrency (real, separate DB connections racing via `asyncio.gather` over
  real HTTP) — see finding #3 above.
- **Rate limits**: `[FIXED 08-14]` now Redis-backed and distributed across replicas (finding
  #1), with graceful in-memory fallback if Redis is briefly unreachable (see "New findings
  from the fix pass" — this fallback is itself load-bearing, not optional polish). Tested:
  10 requests succeed, 11th 429s (unchanged, still single-process for that specific test);
  two-replica state-sharing via Redis now also tested; a real-Redis-outage scenario is now
  tested too.
- **Secret exposure**: `[FIXED 08-14]` redaction lists exist in all 3 services and are now
  directly tested (finding #7) — every listed key confirmed scrubbed, non-listed keys
  confirmed passed through; gitleaks has still never run for real (no CI run yet).
- **Admin authentication**: logic solid and well-tested; TLS termination now exists (Caddy,
  finding #5) but has not been run against a real domain — see status table row 7.
- **Payment webhook security**: signature verification and idempotency are correctly
  implemented and tested — but only self-consistently against the mock provider. No real
  provider integration exists to validate the abstraction against (finding under #8).

## What IS genuinely solid

Worth stating plainly so this document isn't read as "nothing works": the application-layer
logic — request validation, business rules, the service/repository layering, the DB
transaction fix, webhook idempotency, RBAC, audit logging, the routing engine's aggregation
algorithm, the HTTP contract between backend and vpn-agent (proven with a real live
cross-process HTTP exchange, not just mocks) — is thoroughly exercised and was actively
debugged against real (if narrow) execution, including finding and fixing a bug where
production data would never have persisted at all. That is a meaningfully different, better
starting point than "wrote it and hoped." The gap this document is about is specifically the
boundary between "this code is correct" and "this has touched the real infrastructure it's
meant to run on" — which, for a VPN service, is an unusually large and consequential boundary
(a kernel network interface, a real payment processor, a real Telegram token) that no amount
of local testing on a laptop can close.

**As of the 2026-08-14 fix pass**, that statement extends a step further: the 8 fixes were
not just written but each proven with a test that exercises the *actual* failure mode being
closed (a real IntegrityError under genuine concurrency, a real refused TCP connection to
Redis, a real re-raised exception through the real middleware stack) — and that process
caught two additional real bugs (the Redis-outage-crashes-everything issue and the lost
`request_id` on 500s) that pure code review would not have surfaced. That is direct evidence
for this document's own thesis: tests that exercise real behavior find real bugs; tests that
only check the happy path or synthetic fixtures do not.

## Remaining blockers for first real VPS deployment

Everything below is still true after the fix pass — these are infrastructure-touching steps
that categorically cannot be completed inside this sandbox (no Docker, no real Linux host,
no public IP, no DNS control), not further code changes:

1. **A real Linux VPS** (Ubuntu 22.04+ recommended) with a public IP, for the control plane.
2. **A second real Linux host** (or more), for the first VPN exit server — reachable over
   SSH, for `infrastructure/ansible/site.yml`.
3. **Two DNS records** (A, and AAAA if the host has public IPv6) pointing at the control
   plane host, for Caddy's automatic HTTPS — see docs/deployment.md's "TLS / reverse proxy"
   section for the exact sequencing (DNS must resolve *before* Caddy starts, or the ACME
   challenge fails).
4. **Docker + Docker Compose installed** on the control-plane host (this sandbox has
   neither, so `docker build`/`docker compose up` have literally never been run against any
   of this repository's images — including the new `docker-compose.prod.yml`/Caddy setup).
5. **Real secrets generated** for every `change-me*` placeholder in `.env` (the backend
   already refuses to start in production with any left in place — see docs/security.md).
6. **A real Telegram bot token** from @BotFather, and a decision on webhook vs. polling mode
   for the bot at any scale beyond one instance (see docs/deployment.md's scaling notes).
7. **A real payment provider integration** (YooKassa/Cryptomus/Stripe/...) — every one is
   currently `NotImplementedError`; the mock provider is fine for everything up to this
   point but real money cannot move through this system yet.
8. **The first `alembic upgrade head` against real Postgres, and the first real WireGuard
   peer on a real `wg0` interface** — both are now *structurally* verified (the new
   `tests/postgres/` package, and the existing `vpn-agent` test suite's fake-runner
   coverage) but neither has touched the real thing. Both are expected to work based on that
   coverage — neither is confirmed.

None of these are optional "nice to haves" — they are the literal definition of "this has
never run in production," and closing them is what the next phase of work looks like.
