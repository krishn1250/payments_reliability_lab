# ADR 0004: Probes don't depend on the database

**Status:** accepted

## Context
A common pattern is to make readiness or liveness run `SELECT 1`.

## Decision
- **Liveness** (`/healthz`): process and event loop only.
- **Readiness** (`/readyz`): app started and schema initialized. No DB ping.
- **Startup**: same endpoint as readiness, up to 120 s, so a pod starting
  during a failover waits instead of being killed.

## Reasoning
During a DB failover every pod's DB check fails at the same moment.
- If **liveness** checks the DB, kubelet restarts every pod. Recovery now
  needs both the DB *and* every app pod to come back, with cold pools.
- If **readiness** checks the DB, every pod leaves the Service. Clients get
  connection refused instead of a clean `503 Retry-After`, and the retries
  inside the app that could have hidden a 10s failover never get a chance.

Keeping pods in rotation and letting the app retry and then return 503 gives
clients a consistent, retryable answer. Chaos experiment 3 (DB partition)
tests this: the app should recover with zero restarts.

## When this would be wrong
If one pod has a broken connection that others don't (bad node, local DNS),
taking just that pod out is right. A smarter readiness check would fail only
on sustained, pod-local DB errors. Worth revisiting if that happens.
