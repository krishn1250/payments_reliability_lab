# Runbook: PaymentsErrorBudgetFastBurn / SlowBurn

1. **Release in progress?** `kubectl argo rollouts get rollout payments-api -n payments`.
   If a canary is running and its success rate is low, abort: `make abort`.
2. **Database?** Dashboard → "DB retries vs unrecovered errors". Errors > 0 →
   [database-failover](database-failover.md).
3. **Which route?** `sum by (route, status) (rate(http_requests_total{namespace="payments"}[5m]))`
4. **Pods?** `kubectl -n payments get pods -l app=payments-api` (restarts, Ready), `kubectl -n payments logs -l app=payments-api --since=10m | grep -i error`
5. **Chaos still running?** `kubectl -n payments get podchaos,networkchaos,stresschaos,schedule`
