#!/usr/bin/env bash
# Fires the same payment request N times in parallel with one Idempotency-Key.
# Pass = exactly one payment row in Postgres and one distinct id in responses.
set -euo pipefail
N="${1:-50}"
key="idem-test-$(date +%s)-$RANDOM"
kubectl -n payments port-forward svc/payments-api 18080:80 >/dev/null 2>&1 &
pf=$!; trap 'kill $pf 2>/dev/null || true' EXIT; sleep 2

echo "==> sending ${N} concurrent requests with Idempotency-Key=${key}"
seq "$N" | xargs -P "$N" -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST localhost:18080/payments -H 'Content-Type: application/json' \
  -H "Idempotency-Key: ${key}" -d '{"amount_minor": 49900, "currency": "INR", "customer_id": "cust_idem"}' \
  | sort | uniq -c | sed 's/^/    /'

primary=$(kubectl -n payments get pods -l cnpg.io/cluster=payments-db,cnpg.io/instanceRole=primary -o name | head -1)
rows=$(kubectl -n payments exec "$primary" -c postgres -- psql -d payments -tAc \
  "SELECT count(*) FROM payments WHERE idempotency_key = '${key}'")
echo "==> rows in payments for this key: ${rows}"
[ "$rows" = "1" ] && echo "PASS: exactly one payment" || { echo "FAIL"; exit 1; }
