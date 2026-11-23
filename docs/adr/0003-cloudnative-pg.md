# ADR 0003: CloudNativePG for Postgres

**Status:** accepted

## Context
The point of the lab is to exercise database failover. A single Postgres pod
or a StatefulSet without an operator can't fail over on its own.

## Decision
CloudNativePG with 3 instances (1 primary, 2 streaming replicas), pod
anti-affinity across nodes, the `-rw` Service for the app, and the operator's
PodMonitor for replication metrics.

## Why not
- **Bitnami chart / plain StatefulSet:** no automatic failover.
- **Zalando / Crunchy operators:** capable, but CNPG has no Patroni sidecar,
  uses Kubernetes as the source of truth and is a CNCF project.
- **Managed (Azure Database for PostgreSQL / RDS):** what I'd pick in
  production. Not possible on a laptop, and hides the failover I want to study.

## Consequences
- Replication is asynchronous by default: a failover can lose the last few
  committed transactions. For payments, enable synchronous replication
  (`minSyncReplicas: 1`) and accept the extra write latency. Measuring that
  trade-off is a good follow-up experiment.
- NetworkPolicy here covers the app pods only. A full lockdown of the DB pods
  must also allow the operator (port 8000), replication between instances
  (5432) and instance → API server traffic.
