from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests handled", ["method", "path", "status_code"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "path"]
)
WG_COMMAND_ERRORS_TOTAL = Counter(
    "wg_command_errors_total", "Failed `wg`/`wg-quick` invocations", ["command"]
)
ENABLED_PEERS = Gauge("wg_enabled_peers", "Peers currently tracked as enabled in the local store")
