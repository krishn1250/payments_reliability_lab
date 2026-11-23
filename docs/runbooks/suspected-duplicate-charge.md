# Runbook: suspected duplicate charge

Treat as a sev-1 until disproven.

1. Run `make invariants`. If all pass, the database has no duplicate effects.
2. Look the customer up:
   ```sql
   SELECT id, idempotency_key, amount_minor, status, created_at
   FROM payments WHERE customer_id = '<id>' ORDER BY created_at DESC LIMIT 20;
   ```
   Two rows with different idempotency keys and the same amount close together
   means the **client** generated a new key per retry. That's a client bug:
   the key must be created once per user intent (e.g. per checkout), not per HTTP call.
3. Check the audit trail for one payment:
   ```sql
   SELECT * FROM payment_transitions WHERE payment_id = '<uuid>' ORDER BY at;
   SELECT * FROM webhook_events WHERE payment_id = '<uuid>' ORDER BY received_at;
   ```
4. If an invariant fails, freeze releases, capture the rows, write a postmortem.
