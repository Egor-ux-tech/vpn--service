# xray-agent

`xray-agent` is the VLESS/Reality analogue of `vpn-agent` (see docs/wireguard.md) —
a small privileged-adjacent service that runs on each VLESS exit node and reconciles
Xray-core's live user list to match what the backend asks for. It is a **separate**
codebase and deployable from `vpn-agent`; nothing in `vpn-agent` was modified to build
it (see docs/vless.md's architecture-comparison section for why they stay two services
instead of one shared abstraction).

## Components on a VLESS exit node

Each VLESS node runs two things (deployed by `infrastructure/ansible/site.yml`'s second
play):

1. **Xray-core** (`roles/xray`) — the actual VLESS Reality server, installed as a
   native binary (not Docker), running as its own systemd unit (`xray.service`) under
   an unprivileged `xray` user with only `CAP_NET_BIND_SERVICE` (to bind :443). Its
   config (`/etc/xray/config.json`) is static and **never rewritten for per-user
   changes** — the "vless-reality-in" inbound starts with `"clients": []`, and every
   user add/remove happens exclusively through Xray's HandlerService gRPC API
   (`127.0.0.1:10085`, loopback-only, never in any firewall allowlist).
2. **`xray-agent`** (`xray-agent/`, this document) — a FastAPI service, its own
   systemd unit (`xray-agent.service`), running as a *different* unprivileged user
   with **no special capabilities at all** (unlike vpn-agent's `CAP_NET_ADMIN` or
   Xray's `CAP_NET_BIND_SERVICE` — xray-agent never touches a privileged port or a
   network interface). It's the only process allowed to call Xray's gRPC API.

The backend never talks to Xray directly — only to xray-agent, over HTTPS, HMAC-signed
per request (`X-Signature`/`X-Timestamp`, verified against a secret **distinct from**
`VPN_AGENT_SHARED_SECRET`: `XRAY_AGENT_SHARED_SECRET`). This preserves the same trust
boundary vpn-agent already has: a compromised backend can request user changes but
can't reach Xray's internals directly, and a compromised VLESS node's credential can't
be replayed against a WireGuard node or vice versa.

## gRPC integration

Xray-core exposes no CLI for user management (verified against XTLS/Xray-core's own
documentation and source — there is no stock `xray api adduser`/`rmuser` subcommand);
the only supported mechanism is the `HandlerService` gRPC API
(`app/proxyman/command` package), calling `AlterInbound` with an `AddUserOperation`/
`RemoveUserOperation` wrapped in a `TypedMessage`, plus `GetInboundUsers`/
`GetInboundUsersCount` for read/health queries.

`xray-agent/proto/*.proto` is a **trimmed, wire-compatible subset** of xray-core's own
`.proto` files (`app/proxyman/command/command.proto`, `common/protocol/user.proto`,
`common/serial/typed_message.proto`, `proxy/vless/account.proto`), fetched verbatim
from `github.com/XTLS/Xray-core@main` and trimmed to only the messages/RPCs xray-agent
actually calls — the full `HandlerService` also manages inbound/outbound *configs*
(`AddInbound`, `ListOutbounds`, ...), whose message types pull in a large, unrelated
transitive dependency graph (`core.InboundHandlerConfig`) that has nothing to do with
VLESS user lifecycle. gRPC dispatches by exact `/package.Service/Method` path and each
message's wire format is defined solely by its own field numbers, so a client stub
declaring only a subset of a service's RPCs is fully wire-compatible with the real
server for the calls it does make — this was verified end-to-end with a live
`grpc.aio` round trip against a fake `HandlerServiceServicer` implementing the same
proto (`tests/test_grpc_handler_client.py`), not just compiled and assumed correct.

Compiled Python stubs live in `app/xray_proto/` (generated via `grpc_tools.protoc`,
committed rather than generated at install time — see `scripts/generate_proto.sh` to
regenerate after changing anything under `proto/`).

**What was NOT independently verified against a real Xray-core binary**: the exact
runtime behavior of `AlterInbound`/`GetInboundUsers` against a live process (only a
fake in-process servicer was exercised — see "Known limitations" below).

## Xray Reality configuration

VLESS + Reality + TCP + `xtls-rprx-vision`, port 443, `shortIds: [""]` (a single empty
entry, which makes the client-side `sid` parameter always omittable — confirmed
against the official REALITY spec during the VLESS/Happ research spike). The
camouflage/target SNI (`xray_reality_camouflage_sni` in
`infrastructure/ansible/group_vars/all.yml.example`) is a **placeholder**
(`www.example.com`) — choosing a real one is a threat-model/operational decision for
whoever deploys this, not a technical default; see the comment next to that variable
before deploying for real.

The Reality keypair is generated once, idempotently, by Ansible (`xray x25519` —
verified output format: `Private key: <b64url>` / `Public key: <b64url>`, against
XTLS/Xray-core's own command documentation and a real discussion thread showing actual
CLI output). **The private key never leaves the node's filesystem**
(`/etc/xray/reality_private_key`, mode 0600, owned by the unprivileged `xray` user) —
it is read directly by Xray-core via the templated `config.json`, never sent to the
backend, never handled by xray-agent's own code at all. Only the **public** key is
printed by the Ansible run and registered with the backend
(`VLESSServerConfig.reality_public_key`, POST /api/v1/vless-servers) — see
docs/vless.md's Reality key management section for the full rationale.

## User lifecycle

Xray has no native "disabled" state and no `AddUserOperation` idempotency of its own —
`xray-agent` provides both on top:

| Backend operation | xray-agent endpoint | What happens |
|---|---|---|
| Create / re-enable | `POST /users` | Idempotent: upserts the desired-state row; only calls `AddUserOperation` if the email isn't already live on the inbound |
| Disable / revoke / expire | `DELETE /users/{uuid}` | Idempotent: `RemoveUserOperation` if live, then deletes the desired-state row; deleting an already-absent uuid is a no-op success |
| Rotate UUID | `POST /users/{uuid}/rotate` | `RemoveUserOperation`(old) → `AddUserOperation`(new), same `email`/device identity, one atomic-from-the-caller's-view call |
| List | `GET /users` | Returns the local desired-state store's contents |
| Health | `GET /health`, `GET /ready`, `GET /status` | `/health` is pure liveness (no Xray call); `/ready`/`/status` perform a real gRPC round trip (`GetInboundUsersCount`) — an agent that's up but can't reach Xray is reported as **not** ready |

`email` (Xray's own per-user identity key for `RemoveUserOperation`) is derived
deterministically as `device-{device_id}` — never the UUID itself, since the UUID is
the bearer credential and must never end up inside a differently-named field that
key-based log redaction wouldn't catch.

Backend-supplied UUIDs, not agent-generated: `xray-agent` never calls `uuid4()` itself
— identity generation is a control-plane responsibility (mirroring how `vpn-agent`
never allocates IPs either — that's `DeviceService`/`ip_allocator.py`'s job).

## Reconciliation — why it must be periodic, not just startup

`vpn-agent`'s `PeerReconciler` only reconciles on its own startup, because WireGuard
peers persist across a `wg0` restart independently of the agent (`SaveConfig=true`).
**Xray-core has no equivalent** — a bare process restart (crash, OOM, manual bounce)
wipes its in-memory user list back to the statically-templated config's empty
`clients: []`, with nothing on disk to recover from. `xray-agent`'s `UserReconciler`
therefore reconciles **both at startup and on a periodic timer**
(`RECONCILIATION_INTERVAL_SECONDS`, default 300s) — see `app/xray/reconciler.py`'s
module docstring. Reconciliation is bidirectional: it re-adds anything the desired
state has that Xray's live list is missing (self-healing after an Xray crash), and
removes anything Xray has live that the desired state no longer wants (closes the gap
if a `DELETE /users/{uuid}` call was lost because the agent itself was down when the
backend tried to make it).

## Backend ↔ xray-agent protocol

Same shape as backend ↔ vpn-agent (see docs/wireguard.md): HMAC-SHA256 over the raw
request body, `X-Signature`/`X-Timestamp` headers, a freshness window bounding replay.
Distinct secret (`XRAY_AGENT_SHARED_SECRET`). The backend's `HttpXrayAgentProvider`
(`backend/app/services/vless/xray_agent_provider.py`) retries connection-level
failures (refused/timeout — not 4xx/5xx application errors) up to 3 times with
backoff, which is safe specifically because every mutating xray-agent endpoint is
idempotent.

## Security

- Xray's gRPC API: `listen: 127.0.0.1` only in `config.json`, never on a public
  interface — xray-agent is the only process that can reach it, by network topology,
  not just convention.
- xray-agent's own HTTP API: firewalled to `backend_source_ip` only
  (`roles/xray/templates/nftables.conf.j2`), mirroring vpn-agent's own nftables
  allowlist pattern exactly.
- `/health`, `/ready`, `/metrics` are deliberately unauthenticated (same as vpn-agent)
  — they expose no per-user identifiers, only aggregate counts and liveness; `/users/*`
  requires a valid signature.
- The Reality private key is filesystem-only, 0600, unprivileged owner — never touched
  by xray-agent's own code, never transmitted anywhere.
- VLESS UUIDs are treated as bearer credentials: redacted from logs
  (`app/core/logging.py`'s `_REDACT_KEYS` includes `uuid`/`vless_uuid` in both
  xray-agent and the backend), never embedded inside a differently-named log field
  (see the `email` derivation note above).

## Known limitations

- **Never exercised against a real Xray-core binary** — every test in
  `xray-agent/tests/` runs against either an in-memory fake (`FakeXrayHandlerClient`)
  or a real `grpc.aio` server implementing a fake `HandlerServiceServicer` following
  the same trimmed proto (proves the wire protocol is correct; does not prove Xray's
  actual runtime behavior matches — e.g. whether `AddUserOperation` on an
  already-present email errors or silently succeeds on the real server was not
  observed, hence `xray-agent`'s own check-before-add idempotency logic rather than
  relying on Xray itself being lenient). Requires a real VLESS node to confirm.
- The camouflage SNI is a placeholder — see the Reality configuration section above.
- Reality key **rotation** (as opposed to initial generation) has no Ansible task or
  runbook yet — today it would mean manually removing `reality_private_key`, re-running
  the role, and updating `VLESSServerConfig.reality_public_key` via the admin API.
