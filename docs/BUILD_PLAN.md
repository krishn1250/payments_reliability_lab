# Build plan

Build it in this order and commit at each step. Get each step working before
the next; the problems you hit are your interview stories.

| Step | Build | Done when |
|---|---|---|
| 1 | `services/payments-api/app/domain.py` + `tests/test_domain.py` | `pytest tests/test_domain.py` green |
| 2 | API + db.py, run against `docker run postgres:16` | integration tests green locally |
| 3 | `bootstrap/` + Argo CD + root app with only kube-prometheus-stack | Grafana opens |
| 4 | CNPG app + `database.yaml` | `kubectl get cluster -n payments` healthy, 3 pods |
| 5 | Deployment (not Rollout yet), Service, PodMonitor, loadgen | dashboard shows traffic |
| 6 | Kill the primary by hand (`kubectl delete pod`) before adding retries | you've seen it fail, note the numbers |
| 7 | Add `with_retry` + pool `check`, repeat step 6 | errors mostly gone; write postmortem #1 comparing before/after |
| 8 | Argo Rollouts, convert to Rollout, AnalysisTemplate | `make release-bad` aborts |
| 9 | Chaos Mesh + experiments 2–6 | experiments doc filled in |
| 10 | OpenTelemetry SDK + Collector + Tempo | a failed request's trace shows its `db.retry` events |
| 11 | Terraform for cluster + Argo CD (replace the manual bootstrap) | `make down && make up` rebuilds everything |
| 12 | Alerts, runbooks, invariant script, CI | CI green, alerts visible in Prometheus |

Step 6→7 is the most valuable thing in this repo: a measured before/after of
the same failure.
