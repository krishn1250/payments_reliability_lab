#!/usr/bin/env bash
# The webhook signing secret is the only secret not generated in-cluster
# (CNPG generates the DB password). Kept out of Git on purpose.
# In a real setup this comes from Vault/Key Vault via External Secrets.
set -euo pipefail
kubectl create namespace payments --dry-run=client -o yaml | kubectl apply -f -
if kubectl -n payments get secret payments-webhook >/dev/null 2>&1; then
  echo "payments-webhook already exists"
else
  kubectl -n payments create secret generic payments-webhook --from-literal=secret="whsec_$(openssl rand -hex 24)"
fi
