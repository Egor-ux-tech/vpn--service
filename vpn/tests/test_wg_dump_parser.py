from app.wireguard.interface import parse_wg_dump

SAMPLE_DUMP = (
    "privkeyplaceholder\tpubkeyplaceholder\t51820\toff\n"
    "PEERPUBKEY1\t(none)\t203.0.113.5:51820\t10.66.0.2/32\t1700000000\t1024\t2048\t25\n"
    "PEERPUBKEY2\t(none)\t(none)\t10.66.0.3/32\t0\t0\t0\toff\n"
)


def test_parse_wg_dump_skips_interface_line():
    peers = parse_wg_dump(SAMPLE_DUMP)
    assert len(peers) == 2


def test_parse_wg_dump_extracts_handshake_and_traffic():
    peers = parse_wg_dump(SAMPLE_DUMP)
    active = next(p for p in peers if p.public_key == "PEERPUBKEY1")
    assert active.rx_bytes == 1024
    assert active.tx_bytes == 2048
    assert active.latest_handshake is not None
    assert active.allowed_ips == ["10.66.0.2/32"]


def test_parse_wg_dump_handles_never_connected_peer():
    peers = parse_wg_dump(SAMPLE_DUMP)
    never_connected = next(p for p in peers if p.public_key == "PEERPUBKEY2")
    assert never_connected.latest_handshake is None
    assert never_connected.endpoint is None


def test_parse_wg_dump_empty_output_returns_empty_list():
    assert parse_wg_dump("") == []
