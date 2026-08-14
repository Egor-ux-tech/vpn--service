"""Guards the exit-server IPv6 config against silent regression — see docs/wireguard.md's
"IPv6 strategy" section for the full reasoning. This is plain text-content assertions on
the Ansible templates/tasks, not a Jinja2 render or an Ansible run (no Ansible dependency
in this Python venv, and none is needed): the properties that matter here are simple
enough to check as substrings, and the point is to fail loudly if someone flips the
sysctl back on, or removes the nftables drop rules, without also building real IPv6
support (a matching `ip6 nat` table, IPv6-addressed peers, etc).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WIREGUARD_ROLE = REPO_ROOT / "infrastructure" / "ansible" / "roles" / "wireguard"


def test_ipv6_forwarding_is_disabled_on_exit_servers() -> None:
    tasks = (WIREGUARD_ROLE / "tasks" / "main.yml").read_text()
    assert "net.ipv6.conf.all.forwarding = 0" in tasks, (
        "exit servers must not forward IPv6 — this service has no IPv6 NAT table and no "
        "IPv6-addressed peers, so a forwarded IPv6 packet can only be a bug, not a feature"
    )
    assert "net.ipv6.conf.all.forwarding = 1" not in tasks


def test_ipv4_forwarding_is_still_enabled() -> None:
    """The IPv6 check above must not have collaterally disabled the IPv4 forwarding the
    tunnel actually needs to function."""
    tasks = (WIREGUARD_ROLE / "tasks" / "main.yml").read_text()
    assert "net.ipv4.ip_forward = 1" in tasks


def test_nftables_drops_ipv6_transit_through_wg0() -> None:
    nftables = (WIREGUARD_ROLE / "templates" / "nftables.conf.j2").read_text()
    assert 'meta nfproto ipv6 iifname "wg0" drop' in nftables
    assert 'meta nfproto ipv6 oifname "wg0" drop' in nftables


def test_nat_table_is_ipv4_only() -> None:
    """`table ip nat` (IPv4-only), never `table ip6 nat` — adding IPv6 masquerade without
    also doing everything else IPv6 support requires (see docs/wireguard.md) would forward
    packets with a private, unmasqueraded source address that upstream routers just drop,
    for no actual benefit and a false sense of dual-stack support."""
    nftables = (WIREGUARD_ROLE / "templates" / "nftables.conf.j2").read_text()
    assert "table ip nat {" in nftables
    # Checked as a real declaration, not a bare substring: the file's own comments
    # deliberately mention "ip6 nat" in prose (explaining what adding IPv6 support would
    # require), which would false-positive on a plain "in" check.
    assert "table ip6 nat {" not in nftables
