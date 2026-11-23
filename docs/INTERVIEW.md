# Interview guide

## 60-second pitch
"I built a payments service and then tried to break it. It's idempotent end to
end: an Idempotency-Key with a unique constraint and ON CONFLICT for creates,
and signed webhooks deduplicated by event id and applied in one transaction
with a row lock and a state machine. On top of that, releases go out as Argo
Rollouts canaries that query Prometheus for just the canary's pods and roll
back automatically. The database is a 3-node CloudNativePG cluster, and every
request is traced with OpenTelemetry, so each DB retry shows up on the trace. Then I ran
chaos experiments (killing the primary under load, partitioning the database,
bad releases) and after each one checked five business invariants in Postgres.
The result I'm proudest of is the before/after on DB failover: adding
retries with backoff took user-facing errors from ___ to ___, and it's only
safe because every write is idempotent."

(Fill in the blanks with your real numbers from the build plan, step 6→7.)

## Questions to be ready for

**What is idempotency and why does it matter for payments?**
Doing an operation twice has the same effect as doing it once. Networks
time out after the server already committed, so clients must retry, and
without idempotency every retry can be a second charge.

**Why ON CONFLICT instead of checking first?**
Check-then-insert is a race: two requests both see "not found" and both
insert. ON CONFLICT relies on the unique index, so the database guarantees
only one insert wins.

**What if the same key is sent with a different amount?**
We store a hash of the request body with the key and return 422. Silently
returning the old payment would hide a client bug.

**How do you verify webhooks? Why sign the timestamp?**
HMAC-SHA256 over `timestamp.body` with a shared secret, constant-time compare,
5-minute window. If the timestamp weren't signed, someone could replay an old
captured webhook with a fresh timestamp.

**Why return 200 for a duplicate or invalid event?**
The provider retries on non-2xx. The event *was* handled (recorded and
ignored), so 200 stops pointless retries. Unknown payment returns 404 on
purpose so the provider retries later.

**Why doesn't liveness check the database?**
See ADR 0004: a DB outage would restart every pod at once and slow recovery.

**How does the canary analysis only look at canary pods?**
PodMonitor copies `rollouts-pod-template-hash` into a `revision` label; the
Rollout passes the canary's hash to the AnalysisTemplate.

**What's the blast radius of a bad release?**
~25% of traffic for ~60–90s. Smaller with a traffic router (5% steps) or by
adding a 0-traffic step with header-based routing first.

**Async replication: can you lose a payment in failover?**
Yes, the last few transactions. Options: synchronous replication
(`minSyncReplicas`) at a write-latency cost, or reconcile with the provider.
For payments I'd choose sync replication and measure the cost.

**Why tail sampling? Why put a Collector in the middle?**
Head sampling at 10% throws away 90% of your error traces. Tail sampling waits
for the whole trace, then keeps every error, every slow request and every
idempotent replay, plus 10% of the rest. The Collector keeps the app
vendor-neutral and centralizes sampling, batching and buffering. Caveat:
all spans of a trace must reach the same Collector, so at scale you add a
load-balancing tier keyed on trace ID.

**Metrics vs logs vs traces?**
Metrics tell you something is wrong and how much (cheap, aggregated, alertable).
Traces tell you where in one request it went wrong. Logs give the detail at
that point. Here every error response carries a trace ID that links them.

**Why retry only some errors?**
Retrying a constraint violation or bad input never succeeds and just adds
load. Only connection/failover/serialization SQLSTATEs are retried, with
jittered backoff so all pods don't retry in lockstep.

## Resume bullet (put your real numbers in)
- Built a payments reliability lab on Kubernetes: idempotent API and webhook
  processing (Postgres unique constraints, HMAC verification, state machine),
  Argo Rollouts canaries with Prometheus analysis that auto-rolled back faulty
  releases in ~90s, CloudNativePG failover, and OpenTelemetry tracing with
  tail sampling (Collector + Tempo); chaos experiments (Chaos Mesh)
  cut failover errors from X% to Y% with zero duplicate charges across N runs.
