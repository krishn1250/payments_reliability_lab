# Chaos experiments

For each one: write the hypothesis, run it with `make chaos-…` (the script
prints start/end times and runs the invariant check), set Grafana to that
time range, fill in "Observed", and write a postmortem for anything surprising.
The in-cluster load generator is always running, so there's always traffic.

---

## 1. Bad release is caught by the canary
- **Hypothesis:** `make release-bad` (20% errors) aborts at the 25% step within
  ~90s. Overall error rate peaks around 5% (25% of traffic × 20%) and
  `PaymentsErrorBudgetFastBurn` may fire briefly.
- **Observed:** time to abort ___ · peak overall error rate ___ · budget used ___
- **Then:** `make release-slow`. Which metric aborts it, and how fast?

## 2. Postgres primary killed under load
- **Hypothesis:** a replica is promoted within 30s. Retries absorb most of the
  gap: DB retries spike, unrecovered errors < 1% of requests in that minute,
  zero app restarts, all invariants pass.
- **Run:** `make chaos-db-primary`
- **Observed:** failover time ___ · retries ___ · 5xx ___ · restarts ___ · invariants ___
- **Traces:** open a failed request from the dashboard's "Traces" row. How many
  `db.retry` events does it have, which SQLSTATE, and how long did it wait in total?
  Compare with a request that succeeded after retrying.
- **Follow-up:** with `minSyncReplicas: 1`, does write latency change? Is any data lost without it?

## 3. App cut off from the database for 45s
- **Hypothesis:** requests fail with 503 after ~6s of retrying; liveness keeps
  passing so **no pods restart**; traffic recovers within seconds of the
  partition ending; invariants pass.
- **Run:** `make chaos-db-partition`
- **Observed:** first 503 at ___ · recovery ___ · restarts ___ · invariants ___
- **Contrast:** temporarily add a DB check to `/healthz`, re-run, and compare
  recovery time. (This is the experiment behind ADR 0004.)

## 4. 150ms DB latency
- **Hypothesis:** p95 crosses 300ms; availability unchanged. A release started
  during this window would be aborted on p95 even though it's healthy.
- **Run:** `make chaos-db-latency`, and `make release-good` in parallel.
- **Observed:** p95 ___ · did the healthy release abort? ___
- **Question:** is that the right behaviour? (Arguments both ways.)
- **Traces:** pick a slow trace. How much of the time is in SQL spans vs the app?
  That breakdown is what tells you "it's the database/network, not the code".

## 5. App pods killed every 30s
- **Hypothesis:** with 4 replicas, PDB `minAvailable: 3`, readiness and preStop,
  5xx stays at ~0.
- **Run:** `make chaos-app-pods`
- **Observed:** 5xx ___ · any client retries? ___

## 6. CPU stress
- **Hypothesis:** p95 rises but stays under 300ms because there's no CPU limit
  and requests guarantee 100m.
- **Run:** `make chaos-cpu`
- **Observed:** p95 ___

## 7. Idempotency under pressure
- **Hypothesis:** during experiment 2, `make test-idempotency` still produces exactly one row.
- **Observed:**
