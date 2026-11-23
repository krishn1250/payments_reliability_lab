from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter("http_requests_total", "HTTP requests.", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2.5, 5),
)
PAYMENTS_CREATED = Counter("payments_created_total", "New payments created.", ["currency"])
IDEMPOTENT_REPLAYS = Counter("payments_idempotent_replays_total", "Requests answered from an existing idempotency key.")
IDEMPOTENCY_MISMATCH = Counter("payments_idempotency_key_mismatch_total", "Idempotency key reused with a different payload.")
WEBHOOKS = Counter("payments_webhook_events_total", "Webhook events by outcome.", ["type", "outcome"])
DB_RETRIES = Counter("payments_db_retries_total", "Transient DB errors that were retried.")
DB_ERRORS = Counter("payments_db_errors_total", "DB errors that were not recovered.", ["error"])
BUILD_INFO = Gauge("app_build_info", "Build metadata.", ["version"])
