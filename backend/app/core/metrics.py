"""Prometheus metrics. Counters/histograms are updated inline as requests are handled;
gauges that reflect current DB state (active users, active peers, ...) are computed
on-demand each time /metrics is scraped (see api/v1 mount in main.py) rather than kept
continuously in sync, which keeps this module free of background-task bookkeeping.
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

API_ERRORS_TOTAL = Counter(
    "api_errors_total",
    "Application errors returned to clients",
    ["error_code"],
)

VPN_PROVISIONING_ERRORS_TOTAL = Counter(
    "vpn_provisioning_errors_total",
    "Errors while provisioning/mutating a WireGuard peer via the vpn-agent",
    ["operation"],
)

VLESS_PROVISIONING_ERRORS_TOTAL = Counter(
    "vless_provisioning_errors_total",
    "Errors while provisioning/mutating a VLESS user via xray-agent",
    ["operation"],
)

DB_QUERY_DURATION_SECONDS = Histogram(
    "db_query_duration_seconds",
    "Database query latency in seconds, as observed by the SQLAlchemy engine",
)

ACTIVE_USERS = Gauge("vpn_active_users", "Users with status=active")
ACTIVE_SUBSCRIPTIONS = Gauge("vpn_active_subscriptions", "Subscriptions with status=active")
ACTIVE_DEVICES = Gauge("vpn_active_devices", "Devices with status=active")
ONLINE_SERVERS = Gauge("vpn_online_servers", "VPN servers with status=online")
ONLINE_PEERS = Gauge("vpn_online_peers", "VPN peers with status=active")
