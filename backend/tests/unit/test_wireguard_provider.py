from app.services.vpn.wireguard_provider import WireGuardProvider


def test_build_client_config_full_vpn_includes_default_route():
    provider = WireGuardProvider(shared_secret="s", dns_servers=["1.1.1.1"])

    config = provider.build_client_config(
        private_key="PRIVATE",
        assigned_ip="10.66.0.2/32",
        server_public_key="SERVERPUB",
        server_endpoint="vpn.example.com:51820",
        allowed_ips=["0.0.0.0/0", "::/0"],
        dns=["1.1.1.1", "1.0.0.1"],
    )

    assert "PrivateKey = PRIVATE" in config
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in config
    assert "Endpoint = vpn.example.com:51820" in config
    # never accidentally echo the value under a misleading key
    assert config.count("PRIVATE") == 1


def test_build_client_config_never_logs_or_duplicates_private_key(caplog):
    provider = WireGuardProvider(shared_secret="s", dns_servers=["1.1.1.1"])
    provider.build_client_config(
        private_key="SUPER-SECRET",
        assigned_ip="10.66.0.3/32",
        server_public_key="SERVERPUB",
        server_endpoint="vpn.example.com:51820",
        allowed_ips=[],
        dns=[],
    )
    assert "SUPER-SECRET" not in caplog.text
