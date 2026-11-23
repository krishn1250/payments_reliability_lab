# Runbook: PaymentsCanaryAborted

**Meaning:** canary analysis failed and Argo Rollouts aborted. Stable pods
already serve 100% of traffic. **User impact has stopped;** this is a ticket,
not a page.

1. See which metric failed:
   ```bash
   kubectl argo rollouts get rollout payments-api -n payments
   kubectl -n payments get analysisrun --sort-by=.metadata.creationTimestamp | tail -3
   kubectl -n payments describe analysisrun <name>     # measurements and values
   ```
2. Compare canary vs stable on the dashboard (row "Canary vs stable").
   Canary-only problem → the release. Both bad → something else (DB, node);
   the release may be fine, re-run it after fixing.
3. Get Git back in sync with what's running: `git revert <release commit> && git push`.
   Until you do, Argo CD shows the Rollout as Degraded.
4. Fix, then release again. Never `kubectl argo rollouts promote --full` past a
   failed analysis without knowing why it failed.
