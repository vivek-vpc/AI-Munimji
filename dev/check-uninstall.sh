#!/usr/bin/env bash
# Does uninstalling the app remove what installing it added? Uses a throw-away site (check.localhost) with ERPNext only:
#   A = before the app, B = with the app, C = after the uninstall, D = after installing it again.
# The result that matters: A == C (nothing left behind) and B == D (installing again gives the same).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/check-uninstall.sh
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
CHECK=check.localhost
OUT=/tmp/munimji-check
mkdir -p "$OUT"

snapshot() { SITE=$CHECK bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/snapshot.py" "$OUT/$1.json" >/dev/null; }

# always from a fresh site, so that A really is "ERPNext only" (set KEEP=1 to reuse the site)
if [ -d "sites/$CHECK" ] && [ "${KEEP:-0}" != "1" ]; then
  step "drop-site $CHECK" bench drop-site "$CHECK" --force --no-backup --db-root-password 123
fi
bash "$REPO/dev/make-site.sh" "$CHECK"

snapshot A
step "install-app ai_munimji" bench --site "$CHECK" install-app ai_munimji
snapshot B
step "uninstall-app ai_munimji" bench --site "$CHECK" uninstall-app ai_munimji --yes --no-backup
snapshot C
step "install-app ai_munimji again" bench --site "$CHECK" install-app ai_munimji
snapshot D

echo
echo "=== A (before the app) -> C (after the uninstall): what the uninstall left behind"
python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/A.json" "$OUT/C.json" || true
echo
echo "=== B (with the app) -> D (after installing it again): does a second install give the same?"
python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/B.json" "$OUT/D.json" || true
echo
echo "=== A -> B: what the install added"
python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/A.json" "$OUT/B.json" || true
