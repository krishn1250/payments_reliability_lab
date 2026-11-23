#!/usr/bin/env bash
# Runs one experiment: records the start time, applies it, waits, cleans up,
# then checks invariants. Paste the timestamps into your postmortem and set
# the Grafana time range to them.
#   ./scripts/chaos.sh db-primary-kill 120
set -euo pipefail
name="${1:?usage: $0 <experiment> [observe_seconds]}"
wait_s="${2:-180}"
file="chaos/${name}.yaml"
[ -f "$file" ] || { echo "no such experiment: $file"; ls chaos; exit 1; }

start=$(date -u +%FT%TZ)
echo "==> ${name} start ${start}"
if [[ "$name" == db-primary-kill ]]; then
  echo "    primary before: $(kubectl -n payments get pods -l cnpg.io/instanceRole=primary -o name)"
fi
kubectl apply -f "$file"
echo "==> observing for ${wait_s}s (Grafana: payments · reliability)"
sleep "$wait_s"
kubectl delete -f "$file" --ignore-not-found
end=$(date -u +%FT%TZ)
echo "==> ${name} end ${end}"
if [[ "$name" == db-primary-kill ]]; then
  echo "    primary after:  $(kubectl -n payments get pods -l cnpg.io/instanceRole=primary -o name)"
fi
echo "==> app restarts: $(kubectl -n payments get pods -l app=payments-api -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{" "}{end}')"
./scripts/check-invariants.sh
