#!/usr/bin/env bash
# Does an upgrade keep what a person has? A throw-away site gets the code of an earlier version of the app (a git tag, v0.1.1 unless you name another), the settings a person would have by then,
# and then the code of the working tree and `bench migrate`, twice. Required (exit code 1 if any fails): the person's settings, the schedule of the stock check and the jobs that were running are
# as they were; the new Telegram parts exist and are off; nothing the old version had is gone; a second migrate changes nothing. The list is dev/scripts/check_upgrade_compare.py.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/check-upgrade.sh [tag]        (about 5 minutes: most of it is ERPNext being installed on the new site; KEEP=1 keeps the site)
#
# The old code is put in front of the editable install with PYTHONPATH, for the commands of the first half only, so that the other sites of the bench keep running the code of the working tree.
set -uo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
FROM=${1:-v0.1.1}
UP=upgrade.localhost
OUT=/tmp/munimji-upgrade
OLD=$OUT/old
mkdir -p "$OUT"
rm -rf "$OLD" && mkdir -p "$OLD"

git -c safe.directory="$REPO" -C "$REPO" archive "$FROM" | tar -x -C "$OLD" || { echo "the tag $FROM was not found in the repository"; exit 1; }
[ -f "$OLD/ai_munimji/__init__.py" ] || { echo "$FROM holds no ai_munimji package"; exit 1; }
echo "old code: $FROM, $(grep -m1 __version__ "$OLD/ai_munimji/__init__.py")"

state() { SITE=$UP bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/upgrade_state.py" "$OUT/$1.json" 2>&1 | tail -1; }

if [ -d "sites/$UP" ] && [ "${KEEP:-0}" != "1" ]; then
  step "drop-site $UP" bench drop-site "$UP" --force --no-backup --db-root-password 123
fi
bash "$REPO/dev/make-site.sh" "$UP" || { echo "the site could not be made"; exit 1; }

echo "=================== the old version, installed ==================="
(
  export PYTHONPATH="$OLD"
  step "install-app ai_munimji ($FROM)" bench --site "$UP" install-app ai_munimji
  SITE=$UP bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/upgrade_seed.py" 2>&1 | tail -1
  state before
)

echo "=================== the working tree, and bench migrate ==================="
step "migrate (the upgrade)" bench --site "$UP" migrate || failed_migrate=1
state after
step "migrate (again)" bench --site "$UP" migrate || failed_migrate=1
state again

echo
echo "=================== required results ==================="
python3 "$REPO/dev/scripts/check_upgrade_compare.py" "$OUT/before.json" "$OUT/after.json" "$OUT/again.json"
result=$?
[ "${failed_migrate:-0}" = "1" ] && { echo "  FAIL  bench migrate did not exit 0"; result=1; }

if [ "${KEEP:-0}" != "1" ]; then
  step "drop-site $UP" bench drop-site "$UP" --force --no-backup --db-root-password 123
fi
exit $result
