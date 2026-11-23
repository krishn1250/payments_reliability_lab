#!/usr/bin/env bash
# Replace YOUR_GITHUB_USER with your GitHub username in the Argo CD apps.
set -euo pipefail
user="${1:?usage: $0 <github-user>}"
grep -rl --exclude-dir=.git YOUR_GITHUB_USER . | while read -r f; do
  sed -i.bak "s/YOUR_GITHUB_USER/${user}/g" "$f" && rm -f "$f.bak"
  echo "updated $f"
done
