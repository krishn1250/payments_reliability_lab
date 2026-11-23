# ADR 0006: Terraform bootstraps, GitOps runs everything else

**Status:** accepted

## Context
Something has to create the cluster and install Argo CD before Argo CD can
manage anything. Doing that with a bash script works once but isn't
repeatable, reviewable or destroyable as a unit.

## Decision
Terraform owns the bootstrap layer only:
1. kind cluster (control plane + N workers)
2. the `payments` namespace and the webhook signing secret (generated, never in Git)
3. Argo CD (Helm)
4. the root Application (via the `argocd-apps` chart)

Argo CD owns everything after that: operators, monitoring, tracing, the app.

## Why not manage everything in Terraform?
- Terraform runs when someone runs it. Argo CD reconciles continuously and
  reverts drift; Terraform only notices drift on the next plan.
- Kubernetes CRs in Terraform (`kubernetes_manifest`) need their CRDs to exist
  at plan time, which breaks fresh-cluster applies. That's why the root app
  goes through a Helm chart.
- Two tools fighting over the same objects is a common source of outages.
  A hard line ("Terraform stops at the root app") avoids it.

## Consequences
- `make down && make up` rebuilds the whole lab from nothing.
- The webhook secret is in Terraform state. Acceptable locally; in production
  the state backend is encrypted and access-controlled, or the secret comes
  from a secret manager instead.
- On AKS/EKS the same split applies: Terraform for the cluster, node pools,
  networking, identities and Argo CD; GitOps for workloads.
