#!/usr/bin/env bash
# Does installing the app twice, migrating and uninstalling it leave a site as it was? Uses a throw-away site (check.localhost) with ERPNext only:
#   A = before the app            B = with the app            B2, B3 = after two `bench migrate`
#   C = after the uninstall       D = after installing it again
#   E = the same on a site that already has the standalone service's fields (E0 after its erp-setup, E1 with the app, E2 after the uninstall, E3 after erp-setup again)
# What is required (exit code 1 if any fails): A == C except the columns that stay; B == B2 == B3; B == D; C is the same after a second round; the uninstall prints what stays; E as in check_coexistence.py.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/check-uninstall.sh        (about 5 minutes: most of it is ERPNext being installed on the new site)
set -uo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
CHECK=check.localhost
OUT=/tmp/munimji-check
mkdir -p "$OUT"
failed=0

snapshot() { SITE=$CHECK bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/snapshot.py" "$OUT/$1.json" >/dev/null; }
# compare <from> <to> <what is claimed> [allowed keys]
compare() {
  local from=$1 to=$2 claim=$3 allow=${4:-}
  echo "--- $from -> $to: $claim"
  if [ -n "$allow" ]; then
    python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/$from.json" "$OUT/$to.json" --allow "$allow"
  else
    python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/$from.json" "$OUT/$to.json"
  fi
  if [ $? -ne 0 ]; then echo "  FAIL  $claim"; failed=$((failed + 1)); else echo "  PASS  $claim"; fi
}
run_script() { SITE=$CHECK bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/$1" 2>&1 | tail -3; }

# always from a fresh site, so that A really is "ERPNext only" (set KEEP=1 to reuse the site)
if [ -d "sites/$CHECK" ] && [ "${KEEP:-0}" != "1" ]; then
  step "drop-site $CHECK" bench drop-site "$CHECK" --force --no-backup --db-root-password 123
fi
bash "$REPO/dev/make-site.sh" "$CHECK" || { echo "the site could not be made"; exit 1; }

# A is "ERPNext only, as migrated once": the first migrate of any site writes two Version rows (Navbar Settings) that have nothing to do with the app
step "migrate (before the app)" bench --site "$CHECK" migrate
snapshot A
step "install-app ai_munimji" bench --site "$CHECK" install-app ai_munimji
snapshot B
step "migrate (1)" bench --site "$CHECK" migrate
snapshot B2
step "migrate (2)" bench --site "$CHECK" migrate
snapshot B3
step "uninstall-app ai_munimji" bash -c "bench --site '$CHECK' uninstall-app ai_munimji --yes --no-backup 2>&1 | tee '$OUT/uninstall.txt'"
snapshot C
step "install-app ai_munimji again" bench --site "$CHECK" install-app ai_munimji
snapshot D

echo
echo "=================== required results ==================="
compare A C "after the uninstall the site is as before the app, except for the columns that stay" "custom_columns,indexes_on_the_reference,docperm_approve_columns"
compare B B2 "a first migrate changes nothing"
compare B2 B3 "a second migrate changes nothing"
compare B D "installing again gives what the first install gave"
echo "--- the uninstall printed what stays"
for needle in "custom_agent_ref" "ai-munimji-engine" "erp-agents erp-setup"; do
  if grep -q "$needle" "$OUT/uninstall.txt"; then echo "  PASS  the output names $needle"; else echo "  FAIL  the output does not name $needle"; failed=$((failed + 1)); fi
done

echo
echo "=================== the columns that stay (A -> C) ==================="
python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/A.json" "$OUT/C.json" --allow custom_columns,indexes_on_the_reference,docperm_approve_columns || true

echo
echo "=================== E: a site that already has the standalone service's fields ==================="
step "uninstall-app ai_munimji (second round)" bench --site "$CHECK" uninstall-app ai_munimji --yes --no-backup
snapshot C2
compare C C2 "a second round of install and uninstall ends in the same place"
echo "(the next line stands in for 'erp-agents erp-setup')"; run_script standalone_fields.py
snapshot E0
step "install-app ai_munimji over the service's fields" bench --site "$CHECK" install-app ai_munimji
snapshot E1
step "uninstall-app ai_munimji" bench --site "$CHECK" uninstall-app ai_munimji --yes --no-backup
snapshot E2
run_script standalone_fields.py
snapshot E3
python3 "$REPO/dev/scripts/check_coexistence.py" "$OUT/E0.json" "$OUT/E1.json" "$OUT/E2.json" "$OUT/E3.json" || failed=$((failed + 1))

echo
echo "=================== for information: A -> B, what the install adds ==================="
python3 "$REPO/dev/scripts/diff_snapshots.py" "$OUT/A.json" "$OUT/B.json" || true

echo
if [ "$failed" -eq 0 ]; then echo "uninstall check: every required result holds"; else echo "uninstall check: $failed required result(s) FAILED"; fi
exit "$failed"
