# ADR 0005: Distributed tracing with OpenTelemetry and tail sampling

**Status:** accepted

## Context
Metrics told us *that* errors spiked during a DB failover. They couldn't tell
us *which* step of a request failed, how many retries it took, or whether a
slow request was slow in Python, in the pool, or in Postgres.

## Decision
- Instrument the app with the OpenTelemetry SDK: FastAPI (one server span per
  request), psycopg (one span per SQL statement), and our own spans for
  `payment.create` and `webhook.process` with business attributes
  (`payment.id`, `payment.idempotent_replay`, `webhook.outcome`).
- Record every DB retry as a span event (`db.retry` with attempt, error type, delay).
- Return `X-Trace-Id` on every response and `trace_id` in error bodies, so a
  support ticket can be turned into a trace in one step.
- Send everything to an **OpenTelemetry Collector**, not directly to the backend.
  The Collector does **tail sampling**:
  keep 100% of errors, 100% of requests > 300 ms, 100% of idempotent replays,
  and 10% of everything else.
- Store traces in **Grafana Tempo**, linked from Grafana next to the metrics.
  Tempo's metrics generator also produces a service graph.

## Why tail sampling instead of head sampling
Head sampling (decide at the start of a request) keeps a random 10%, so it
throws away 90% of the errors, which are exactly the traces you need in an
incident. Tail sampling waits until the trace is complete (10 s) and then
decides, so rare-but-important traces are always kept while storage stays small.

## Why a Collector in the middle
- Apps stay backend-agnostic: switching Tempo for Jaeger, Datadog or Azure
  Monitor is a Collector config change, not a code change.
- Sampling, batching, memory limits and retries live in one place.
- If the backend is down, the Collector buffers; the app never blocks
  (BatchSpanProcessor drops spans rather than slowing requests).

## Consequences
- Tail sampling needs all spans of a trace on the same Collector instance.
  One replica is fine here; at scale you add a first tier with the
  `loadbalancing` exporter routing by trace ID.
- `decision_wait: 10s` means traces appear in Tempo ~10 s late.
- `enable_commenter` adds the trace context as a SQL comment, so slow-query
  logs in Postgres can be matched to traces.
