from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests handled", ["method", "path", "status_code"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "path"]
)
XRAY_COMMAND_ERRORS_TOTAL = Counter(
    "xray_command_errors_total", "Failed Xray HandlerService gRPC calls", ["operation"]
)
ENABLED_VLESS_USERS = Gauge(
    "vless_enabled_users", "VLESS users currently tracked as enabled in the local store"
)
RECONCILIATION_RUNS_TOTAL = Counter(
    "xray_reconciliation_runs_total", "Reconciliation passes run", ["trigger"]
)
RECONCILIATION_DRIFT_TOTAL = Counter(
    "xray_reconciliation_drift_total",
    "Users added or removed on Xray to correct drift during reconciliation",
    ["action"],
)
