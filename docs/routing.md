# Smart VPN / Routing Engine

Split tunneling — routing some traffic through the VPN and the rest direct — is implemented
entirely through WireGuard's own `AllowedIPs` mechanism. There is no packet inspection, no
custom routing protocol, and no in-house crypto: the "engine" is a service that resolves a
user's domain preferences into a CIDR list and hands it to WireGuard the normal way.

## Data model

- **`routing_categories`** — the global catalog (e.g. "Video", "Messengers"), admin-managed.
- **`routing_rules`** — global domain → category mappings (e.g. `youtube.com` → Video,
  `route_type=vpn`), also admin-managed. This is the catalog everyone shares.
- **`user_routing_profiles`** — one row per user: `mode` = `full_vpn` or `smart_vpn`.
- **`user_category_preferences`** — per user, whether a given catalog category is
  VPN-routed for *them* (smart_vpn mode only).
- **`user_custom_domains`** — domains a user adds themselves, outside the catalog, each
  with its own `route_type`.

A user's effective rule set (`RoutingService._resolve_user_domain_rules`) is: every catalog
domain, routed per-domain according to whether the user has that domain's category enabled,
plus all of the user's own custom domains.

## From domain rules to `AllowedIPs`

`FULL_VPN` mode skips DNS entirely — `AllowedIPs = 0.0.0.0/0, ::/0`.

`SMART_VPN` mode (`RoutingEngine.build_allowed_ips`, `backend/app/services/routing/engine.py`):

1. For every domain rule where `route_type == vpn`, resolve both A and AAAA records
   (`DomainResolver`, `dnspython`'s async resolver). Domains rule `direct` are simply never
   resolved — they're left off the list entirely, so the client's own default route (outside
   the tunnel) reaches them, exactly as if the VPN weren't running.
2. Every returned address becomes a `/32` (IPv4) or `/128` (IPv6) network.
3. The full set is aggregated with `ipaddress.collapse_addresses` — adjacent addresses
   legitimately merge into wider CIDRs (e.g. two consecutive `/32`s become a `/31`). This is
   correct aggregation, not a precision loss: the merged block still covers exactly the
   resolved addresses (see `tests/unit/test_routing_engine.py` for the containment-based
   assertions this implies for anyone extending the tests).
4. If a `smart_vpn` user somehow ends up with an *empty* resolved set (e.g. every enabled
   category's domains temporarily fail to resolve), the engine falls back to full-tunnel
   `AllowedIPs` rather than provisioning a peer that can reach nothing.

## Handling CDNs, multiple records, and flaky DNS

- **Multiple A/AAAA records per domain** (CDN-backed domains) are all kept, not just the
  first — this is why step 2 above operates on every returned address, not the first.
- **A transient resolution failure** (timeout, no nameservers, SERVFAIL) does not silently
  drop the domain from the tunnel. `DomainResolver.resolve` accepts a `fallback_ips`
  parameter — a domain that fails to resolve this cycle keeps whatever IPs it resolved to
  last time, rather than disappearing from the AllowedIPs set. A genuine `NXDOMAIN` (the
  domain no longer exists at all) is treated as "no addresses" rather than a failure, since
  retrying wouldn't help.
- **Regeneration is versioned, not mutated in place**: `RoutingService.regenerate_profile`
  always inserts a new `vpn_profiles` row and marks the previous one superseded
  (`is_current=False`) rather than updating a row's `allowed_ips` column — a client reading
  the "current" profile mid-write never observes a half-updated list.

## When a profile gets regenerated

- Automatically, once, when a device is first provisioned.
- On demand via `POST /api/v1/vpn/devices/{id}/profile/refresh` — used when the user changes
  their Smart VPN category/domain selection (the bot calls this after
  `PUT /routing/me/categories` etc.), and useful to re-run periodically for CDN domains
  whose IPs rotate, since nothing else automatically re-resolves them on a timer in the MVP.

## DNS-leak considerations

Only VPN-routed traffic uses the pushed `VPN_DNS` resolvers (set in the WireGuard client
config's `DNS =` line). Direct-routed domains resolve exactly as they would with the VPN
off — the service never overrides the user's own DNS configuration for that traffic, and
never records which domains a user actually visited (`routing_rules`/`user_custom_domains`
describe *categories/domains a user has opted to route via VPN*, not a browsing history —
see docs/security.md's privacy section).

## Extending this

The interface boundary is `RoutingEngine.build_allowed_ips(rules) -> list[str]` — a future,
more sophisticated resolution strategy (e.g. a maintained public IP-range list for a
service, rather than live DNS resolution) is a new implementation behind the same call, not
a rewrite of `RoutingService` or the API layer above it.
