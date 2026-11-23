#!/usr/bin/env bash
# Ship a "release" the GitOps way: edit the Rollout in Git, commit, push.
# Argo CD syncs it, Argo Rollouts runs the canary, analysis decides.
#
#   ./scripts/release.sh v2                 healthy release
#   ./scripts/release.sh v3 --fault 0.2     20% of requests fail -> should abort
#   ./scripts/release.sh v4 --latency 400   +400ms per request  -> should abort
set -euo pipefail
version="${1:?usage: $0 <version> [--fault RATE] [--latency MS]}"; shift
fault=0; latency=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fault) fault="$2"; shift 2 ;;
    --latency) latency="$2"; shift 2 ;;
    *) echo "unknown flag $1"; exit 1 ;;
  esac
done

f=deploy/payments/rollout.yaml
sed -i.bak -E \
  -e "s|(value: )\"[^\"]*\"( +# release:version)|\1\"${version}\"\2|" \
  -e "s|(value: )\"[^\"]*\"( +# release:fault)|\1\"${fault}\"\2|" \
  -e "s|(value: )\"[^\"]*\"( +# release:latency)|\1\"${latency}\"\2|" "$f"
rm -f "$f.bak"
git diff --stat "$f"
git commit -qam "release: payments-api ${version} (fault=${fault}, latency=${latency}ms)"
git push -q
echo "Pushed. Watch it: make watch"
