#!/usr/bin/env bash
# Builds the development bench inside the container: Frappe v16, ERPNext v16, a site, and (when the repository holds one) the ai_munimji app.
# Runs as the user "frappe". Every step is timed into dev/timings.log. Safe to repeat: a step that has been done is skipped.
#   From Windows:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/bootstrap.sh
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh

FRAPPE_REF=${FRAPPE_REF:-version-16}
ERPNEXT_REF=${ERPNEXT_REF:-version-16}
cd /home/frappe/dev

# the named volume is created owned by root
step "own the bench volume" sudo chown frappe:frappe /home/frappe/dev
# git refuses to work in a repository owned by another user, and the bind mount shows every file as root's
git config --global --add safe.directory "$REPO" || true
git config --global --add safe.directory "$REPO/.git" || true

if [ ! -d frappe-bench ]; then
  step "bench init (frappe $FRAPPE_REF)" bench init --skip-redis-config-generation --frappe-branch "$FRAPPE_REF" frappe-bench
fi
cd "$BENCH_DIR"

step "point bench at the service containers" bash -c '
  bench set-config -g db_host mariadb &&
  bench set-config -g redis_cache redis://redis-cache:6379 &&
  bench set-config -g redis_queue redis://redis-queue:6379 &&
  bench set-config -g redis_socketio redis://redis-queue:6379 &&
  sed -i "/redis/d" Procfile'

if [ ! -d apps/erpnext ]; then
  step "get-app erpnext ($ERPNEXT_REF)" bench get-app --branch "$ERPNEXT_REF" erpnext
fi

if [ ! -d "sites/$SITE" ]; then
  step "new-site $SITE" bench new-site --db-root-password 123 --admin-password admin --mariadb-user-host-login-scope=% "$SITE"
  step "install-app erpnext" bench --site "$SITE" install-app erpnext
  step "developer mode on" bash -c "bench --site $SITE set-config developer_mode 1 && bench --site $SITE clear-cache"
fi

# the app of this repository, soft-linked so that edits made on Windows show up at once
if [ -f "$REPO/pyproject.toml" ] && [ ! -e apps/ai_munimji ]; then
  step "get-app ai_munimji (soft link)" bench get-app --soft-link "$REPO"
fi
if [ -e apps/ai_munimji ] && ! bench --site "$SITE" list-apps | grep -qx ai_munimji; then
  step "install-app ai_munimji" bench --site "$SITE" install-app ai_munimji
fi

echo
echo "Versions in this bench:"
bench version
for app in frappe erpnext; do
  echo "$app commit: $(git -C "apps/$app" rev-parse HEAD)"
done
echo "bootstrap finished. Site: http://$SITE:8000  (Administrator / admin) once 'bench start' is running."
