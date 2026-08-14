# Security

## Secrets

Every secret is read from the environment (`pydantic-settings`), never hardcoded. `.env` is
gitignored; `.env.example` ships only placeholder values, each named `change-me*`. The
backend, bot, and vpn-agent all fail to start under `ENVIRONMENT=production` if any secret
still equals its `.env.example` placeholder (`Settings._reject_default_secrets_in_production`
and its per-service equivalents) — a forgotten override is a startup crash, not a silent
insecure deployment.

Never commit: Telegram bot tokens, payment provider keys, `JWT_SECRET`, `ADMIN_SECRET`,
`INTERNAL_SERVICE_TOKEN`, `VPN_AGENT_SHARED_SECRET`, WireGuard private keys, SSH keys.
`infrastructure/ansible/inventory/hosts.ini` and `group_vars/all.yml` (the real ones, not
the `.example` files) are gitignored for the same reason.

## Authentication and authorization

- **Admin panel**: email/password (bcrypt, 72-byte-safe truncation handled explicitly —
  see `core/security.py`) → JWT bearer token. Roles (`SUPERADMIN`/`SUPPORT`/`VIEWER`) are
  checked per-endpoint via `require_admin_role(...)`; nothing "admin" is reachable without
  an explicit role check.
- **Bot → backend**: the bot is a trusted first-party service, not an untrusted client — it
  authenticates itself with a shared `X-Internal-Token` (constant-time compared) and states
  which end-user it's acting for via `X-Telegram-User-Id`. Telegram itself already
  authenticated the human before the update reached the bot; this is not "no auth", it's
  "auth already happened, elsewhere, and we trust the messenger."
- **First admin account**: either `python -m app.scripts.create_admin` (shell/CLI access,
  no HTTP-exposed secret needed) or `POST /auth/admin/bootstrap`, gated by `ADMIN_SECRET`
  *and* a one-time-only check (refuses if any admin already exists) — a leaked
  `ADMIN_SECRET` alone can't mint a second admin once the first one exists.
- **vpn-agent**: every request from the backend is HMAC-signed
  (`X-Signature`/`X-Timestamp`, `VPN_AGENT_SHARED_SECRET`) with a timestamp freshness
  window to bound replay — see docs/wireguard.md.
- **Payment webhooks**: HMAC-signature verified before the body is trusted at all
  (`PaymentProvider.verify_webhook_signature`).

## CSRF

Not applicable in the classical sense: every state-changing backend call requires an
explicit `Authorization: Bearer <token>` header, which a cross-site form/script cannot
attach automatically the way a cookie would be auto-sent. CORS additionally restricts which
origins may even complete the preflight (`BACKEND_CORS_ORIGINS`, no wildcard).

The admin panel does store its JWT in a **non-httpOnly** cookie (see `frontend/lib/auth.ts`)
so that `proxy.ts` can perform an optimistic redirect check server-side — this is a
deliberate trade-off, not an oversight: the cookie is never the actual authorization
boundary (the backend independently validates the Bearer header on every request
regardless of any cookie), so its exposure to XSS only affects UX-level redirect behavior,
not data access, *unless* an XSS also exfiltrates the cookie value and replays it as a
Bearer header — mitigated by the JWT's short expiry (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`
by default) and the security headers below. A production deployment handling more sensitive
admin data than this MVP should consider a stricter session model (e.g. an httpOnly cookie
plus a same-origin BFF that attaches the Bearer header server-side).

## Rate limiting

A default limit (`RATE_LIMIT_DEFAULT`, 100/minute per client IP) applies to every backend
endpoint via `SlowAPIMiddleware`. `/auth/admin/login` (10/minute) and
`/auth/admin/bootstrap` (5/hour) are tighter, since both are credential-stuffing /
brute-force targets.

## Input validation, SQL injection, idempotency

- Every request body is validated by a Pydantic v2 schema before it reaches a service.
- All database access goes through SQLAlchemy's ORM with bound parameters — no raw SQL
  string interpolation anywhere in the codebase (`SELECT 1` in the readiness probe is a
  static literal, not user input).
- The payment webhook is idempotent by `(provider, external_payment_id)`: a replayed event
  is acknowledged without re-applying subscription activation
  (`PaymentService.handle_webhook`, tested in
  `backend/tests/integration/test_subscriptions_and_payments.py`).
- Every write happens inside the request's single DB transaction
  (`app/db/session.py::get_db` commits on a clean request, rolls back on any exception —
  regression-tested directly against the real dependency function in
  `backend/tests/unit/test_db_session_commits.py`, independent of the test suite's own
  transaction-wrapping override, since that override would otherwise mask exactly this bug
  — which it did, once, during development).

## Audit logging

Every admin mutation (`user.status_updated`, `plan.created`/`updated`,
`server.created`/`updated`/`deleted`, `routing_category.created`, `payment.refunded`,
`support_ticket.replied`/`closed`, ...) is recorded to `audit_logs` with the acting admin,
action, target, and metadata — visible via the admin panel's Audit Logs page or
`GET /api/v1/admin/audit-logs`. System-initiated changes (e.g. subscription expiry) are
logged with `admin_id=null` rather than omitted.

## Dependency vulnerability management

`pip-audit` (Python) and `npm audit` (frontend) run in CI on every change to a service's
dependencies (see `.github/workflows/*.yml`) and are re-checked manually before any
dependency bump is merged. During development this caught real, fixable issues:

- `starlette` pinned only transitively through an older `fastapi` range carried several
  published CVEs (PYSEC-2026-161/248/249/1941/1942/2280/2281) — fixed by bumping `fastapi`
  and pinning `starlette>=1.6.0` explicitly in all three Python services, verified against
  the full test suite (a large starlette version jump, so this was not assumed safe — it
  was tested).
- `python-jose` (JWT library) pulled in `ecdsa`, which carries a long-standing,
  maintainer-acknowledged timing side-channel the `ecdsa` project has stated it won't fix.
  The backend only ever used HS256 (HMAC, not ECDSA) JWTs, so the vulnerable code path was
  never actually reachable — but rather than rely on that distinction, `python-jose` was
  replaced with `PyJWT`, which has zero required dependencies for HMAC algorithms and
  doesn't pull in `ecdsa` at all.

## Secure headers

`SecurityHeadersMiddleware` sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a restrictive
`Permissions-Policy`, and HSTS on every backend response.

## Privacy

The service stores the metadata required to operate — which server a device is on, its
assigned IP, subscription state, which routing *categories* a user has enabled — and
nothing more:

- **No browsing history.** `routing_rules`/`user_custom_domains` describe "this category
  should go via VPN," a static preference, never a record of which domains a user actually
  visited or when.
- **No traffic content.** The service is a WireGuard relay; it never inspects, logs, or
  stores payload data.
- **Private keys never persisted** — see docs/wireguard.md.
- Structured logs redact known-sensitive keys (`private_key`, `password`, `token`,
  `secret`, ...) at the logging-processor level in every service, as defense in depth on
  top of simply not passing those values to log calls in the first place.

## Known gaps / accepted MVP trade-offs

- `MockPaymentProvider` is safe for local dev/CI but must never be enabled
  (`PAYMENT_PROVIDER=mock`) in a real production deployment handling real payments.
- The admin panel's JWT-in-cookie trade-off (above) is acceptable for an internal tool with
  short-lived tokens; revisit before exposing the admin panel to a larger or less-trusted
  operator base.
- `starlette.testclient`'s use of `httpx` is itself deprecated upstream (in favor of a
  package named `httpx2`) as of this writing — tracked as a future dependency migration,
  not urgent since it's a test-only warning with no functional or security impact today.
