# WireGuard

The service uses stock WireGuard — no custom cryptography, no modified protocol. This
document covers how a VPN exit server is set up, how peers are provisioned, and how private
keys are handled.

## Components on a VPN exit server

Each exit server runs two things (deployed by `infrastructure/ansible/site.yml`):

1. **`wg0`** — the actual WireGuard interface, managed by `wg-quick`/`systemd`
   (`wg-quick@wg0.service`). Its `[Interface]` section (private key, listen address/port)
   is templated once at provisioning time; peers are added/removed at runtime, never by
   editing this file by hand.
2. **`vpn-agent`** — a small FastAPI service (`vpn/`) running as its own systemd unit
   (`vpn-agent.service`) with `CAP_NET_ADMIN` (not root) that reconciles `wg0`'s peer list
   to match what the backend asks for. It's the *only* thing on the server that runs `wg`
   commands.

The backend (control plane) never touches `wg0` directly — it only talks to the vpn-agent
over HTTP, HMAC-signed per request (`X-Signature`/`X-Timestamp`, verified against
`VPN_AGENT_SHARED_SECRET`, see `vpn/app/core/auth.py`). This means:

- A compromised/buggy control-plane process can request peer changes but can't run
  arbitrary commands on the exit server.
- A single exit server going down doesn't take down billing/user data — those live only in
  the backend's own database.

## Provisioning a new server

```
cd infrastructure/ansible
cp inventory/hosts.ini.example inventory/hosts.ini      # fill in real hosts
cp group_vars/all.yml.example group_vars/all.yml        # fill in real secrets
ansible-playbook -i inventory/hosts.ini site.yml
```

This installs WireGuard + nftables (NAT/forwarding/firewall — see
`roles/wireguard/templates/nftables.conf.j2`), generates the server's own WireGuard
keypair (once, idempotently — `roles/wireguard/tasks/main.yml`), deploys the vpn-agent, and
installs `node_exporter` for host metrics. At the end it **prints the server's public key**
— register the server via the admin panel (or `POST /api/v1/servers`) with that public key,
`endpoint=<host>:<wg_listen_port>`, and the same `internal_network` CIDR you put in the
inventory, then flip its status to `online`. Routing traffic to it before that point simply
never happens — device provisioning only picks servers with `status == online`
(`VPNServerService.pick_best_available`).

## Peer lifecycle

| Action | What happens |
|---|---|
| Create (`POST /devices`) | Backend allocates the next free IP in the server's `internal_network` (`ip_allocator.py`, skipping the gateway address), calls the vpn-agent's `POST /peers`, which generates an X25519 keypair **on the agent** and adds the peer to `wg0`. |
| Disable | Agent removes the peer from the live interface but **keeps its record** — WireGuard itself has no "paused" peer state, so this is implemented as remove-from-interface + keep-in-store (`PeerReconciler.disable_peer`). |
| Enable | Agent re-adds the same public key/IP from its store. |
| Reissue | Old peer is deleted, a **new** keypair is generated — the backend never retains a private key to resend, so "reissue" is always a full credential rotation, not a re-fetch. |
| Revoke/delete | Peer removed from `wg0` and forgotten entirely. |

The vpn-agent also re-applies every enabled peer to the interface on its own startup
(`PeerReconciler.reconcile_on_startup`), so a reboot or service restart is self-healing
without waiting on the backend.

## Private key handling

- Generated **on the vpn-agent**, inside `POST /peers`, using `cryptography`'s X25519
  implementation (not a shelled-out `wg genkey` — see `vpn/app/wireguard/keygen.py` for why
  this is equivalent, and independent of whether `wireguard-tools` is even installed).
- Returned to the backend in that single HTTP response, forwarded straight through to the
  Telegram bot, and never written to the agent's SQLite store, the backend's Postgres
  database, or any log line (`_REDACT_KEYS` in each service's `core/logging.py` strips
  `private_key` even if it ever ended up in a log call by mistake — defense in depth, not
  the primary control).
- A user who loses their config has one option: **reissue**, which rotates to a new
  keypair. There is no "recover my old private key" flow, by design.

## Smart VPN / split tunneling

Handled entirely client-side via WireGuard's own `AllowedIPs` — see docs/routing.md. No
server-side traffic inspection or custom routing protocol is involved.

## IPv6 strategy

**The tunnel is IPv4-only end to end, by deliberate choice — not an oversight, and not
something split across inconsistent partial support.** Concretely:

- Peers are only ever assigned IPv4 addresses (`ip_allocator.py` allocates from each
  server's `internal_network`, which is always an IPv4 CIDR in every server registered via
  the admin panel / `POST /api/v1/servers`). A client's WireGuard interface therefore has
  no IPv6 address of its own.
- The exit server's NAT table only masquerades IPv4 (`table ip nat` in
  `roles/wireguard/templates/nftables.conf.j2` — there is no `table ip6 nat`).
- IPv6 forwarding is disabled at the kernel level on every exit server
  (`net.ipv6.conf.all.forwarding = 0`, `roles/wireguard/tasks/main.yml`), and the nftables
  `forward` chain additionally drops any IPv6 packet on `wg0` explicitly, as defense in
  depth on top of that sysctl and on top of WireGuard's own cryptokey routing (a peer's
  AllowedIPs on the server side is always `[assigned_ip]`, an IPv4 `/32` — WireGuard itself
  rejects any packet from that peer whose source doesn't match, before it would ever reach
  nftables).

**Why not just leave IPv6 alone / unconfigured?** Because "the tunnel doesn't handle
IPv6" and "IPv6 traffic transparently bypasses the tunnel" are very different outcomes for
the user, and only the OS's default routing table decides between them. A dual-stack client
device (the common case — most phones and laptops have both v4 and v6 connectivity) picks a
destination's address family based on what the OS resolver returns and what routes exist;
without an explicit `::/0` route pointed at the VPN interface, any site or app that prefers
IPv6 would silently route around the tunnel entirely, over the client's normal network path
— exposing the user's real IP and unencrypted traffic for exactly the sites they thought
were being tunneled. This is why full-tunnel client configs include `::/0` in `AllowedIPs`
(see `WireGuardProvider.build_client_config`'s default and
`RoutingEngine.full_vpn_allowed_ips`, both covered by
`backend/tests/unit/test_wireguard_provider.py` and `test_routing_engine.py`): it makes the
client OS route all IPv6 traffic *into* the tunnel, same as IPv4. Combined with the
server-side drop above, the practical effect is that IPv6-only destinations are unreachable
while connected — traffic is captured, then discarded, never leaked via the client's normal
path. That fail-closed behavior is the deliberate trade-off versus either leaking (no
`::/0` capture) or forwarding unmasqueraded packets with a private source address that
upstream routers would drop anyway (enabling forwarding without also building real IPv6
support).

**Smart VPN (split tunneling) already computes real IPv6 CIDRs where relevant** —
`RoutingEngine.build_allowed_ips` resolves both A and AAAA records for VPN-routed domains
and aggregates both families into `AllowedIPs` (`backend/app/services/routing/engine.py`,
`dns_resolver.py`). This is intentionally symmetric with the IPv4 case (a domain configured
for VPN routing shouldn't have its IPv6 address quietly excluded) and is forward-compatible
groundwork, but carries no live traffic today for the same reason as above: the client
tunnel interface has no IPv6 address to source packets from, and the server wouldn't
forward them if it did.

**Adding real dual-stack support later** requires all of: IPv6 addresses in each
`VPNServer.internal_network` (or a parallel IPv6 CIDR field), an IPv6 address on the
client's own `[Interface]`, a `table ip6 nat` masquerade rule, IPv6 forwarding re-enabled,
and removing the explicit nftables drop rules — doing only some of these produces the
"forwards but never NATs" failure mode described above, not partial IPv6 support.
