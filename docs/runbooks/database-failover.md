# Runbook: PaymentsDatabaseErrors / PaymentsDbReplicationLag

```bash
kubectl -n payments get cluster.postgresql.cnpg.io payments-db      # phase, current primary
kubectl -n payments get pods -l cnpg.io/cluster=payments-db -L cnpg.io/instanceRole
kubectl -n payments logs -l cnpg.io/cluster=payments-db --tail=50 | grep -iE 'promot|failover|error'
kubectl -n cnpg-system logs deploy/cloudnative-pg-cloudnative-pg --tail=100   # operator decisions
```
(`kubectl cnpg status payments-db -n payments` is nicer if you install the plugin.)

| Symptom | Likely cause | Action |
|---|---|---|
| Phase `Failing over`, errors for < 60s | failover in progress | wait; watch retries vs errors panel |
| Errors continue after a new primary exists | pool holding dead connections, or DNS caching old IP | check app logs; `kubectl -n payments rollout restart` is the last resort, not the first |
| No primary for minutes | operator can't promote (all replicas lagging / PVC issues) | operator logs; check `cnpg_pg_replication_lag` |
| Replication lag > 10s | replica under-resourced or network latency | check node CPU/IO; failover now could lose writes |

After any failover: `make invariants`. If the cluster lost writes (async
replication), compare provider records against `payments` before closing.
