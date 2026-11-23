# ADR 0001: Canary releases with automated analysis (Argo Rollouts)

**Status:** accepted

## Context
A rolling update replaces every pod with the new version as soon as each one
passes readiness. Readiness says "the process is up", not "the release is
correct". A release that returns 20% errors passes readiness and reaches 100%
of traffic in under a minute.

## Decision
Use an Argo Rollouts canary (25 → 50 → 75 → 100%, 2 minutes per step) with
background analysis that queries Prometheus for the canary's own pods:
success rate ≥ 99%, p95 < 300 ms, zero unrecovered DB errors. Two failed
checks in a row abort the rollout and scale the canary to zero.

Metrics are scraped per pod with a PodMonitor that copies
`rollouts-pod-template-hash` into a `revision` label, and the Rollout passes
the canary hash into the analysis (`podTemplateHashValue: Latest`). That
isolates the canary's numbers without a service mesh.

## Alternatives
- **Rolling update + manual watching:** depends on someone watching.
- **Blue/green:** fast cutover and rollback, but 100% of traffic moves at once
  and needs double capacity.
- **Flagger:** similar outcome; Argo Rollouts fits naturally with Argo CD and has a UI.

## Consequences
- Worst case for a bad release: ~25% of traffic sees errors for ~1–1.5 min
  (initial delay + two 30s checks).
- Weight is by pod count without a traffic router: 25% needs 4 replicas.
- After an abort, Git still contains the bad version. The fix is a revert
  commit, which keeps Git the source of truth.
