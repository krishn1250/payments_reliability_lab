#!/usr/bin/env bash
# Business invariants that must hold no matter what chaos you ran.
# Run this after every experiment. Each query must return 0.
set -euo pipefail
primary=$(kubectl -n payments get pods -l cnpg.io/cluster=payments-db,cnpg.io/instanceRole=primary -o name | head -1)
q() { kubectl -n payments exec "$primary" -c postgres -- psql -d payments -tAc "$1"; }

declare -a names=(
  "duplicate payments for one idempotency key"
  "same webhook event applied more than once"
  "status changed without an audit row"
  "applied webhook without a transition"
  "illegal transition in audit trail"
)
declare -a sql=(
  "SELECT count(*) FROM (SELECT idempotency_key FROM payments GROUP BY 1 HAVING count(*) > 1) x"
  "SELECT count(*) FROM (SELECT event_id FROM payment_transitions GROUP BY 1 HAVING count(*) > 1) x"
  "SELECT count(*) FROM payments p WHERE status <> 'pending' AND NOT EXISTS (SELECT 1 FROM payment_transitions t WHERE t.payment_id = p.id AND t.to_status = p.status)"
  "SELECT count(*) FROM webhook_events w WHERE outcome = 'applied' AND NOT EXISTS (SELECT 1 FROM payment_transitions t WHERE t.event_id = w.event_id)"
  "SELECT count(*) FROM payment_transitions WHERE (from_status, to_status) NOT IN (('pending','succeeded'), ('pending','failed'), ('succeeded','refunded'))"
)

echo "Checking against $(q 'SELECT count(*) FROM payments') payments and $(q 'SELECT count(*) FROM webhook_events') webhook events"
fail=0
for i in "${!names[@]}"; do
  n=$(q "${sql[$i]}")
  if [ "$n" = "0" ]; then printf '  PASS  %s\n' "${names[$i]}"; else printf '  FAIL  %s (%s)\n' "${names[$i]}" "$n"; fail=1; fi
done
exit $fail
