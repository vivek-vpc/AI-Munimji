#!/usr/bin/env bash
# Makes another site in the bench: ERPNext installed, optionally this app too. Used for the test site and the throw-away uninstall check.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/make-site.sh test.localhost app    # with the app
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/make-site.sh check.localhost        # ERPNext only
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
NEW=${1:?site name, ending in .localhost}
WITH_APP=${2:-}

if [ -d "sites/$NEW" ]; then
  echo "$NEW exists"
else
  step "new-site $NEW" bench new-site --db-root-password 123 --admin-password admin --mariadb-user-host-login-scope=% "$NEW"
  step "install-app erpnext on $NEW" bench --site "$NEW" install-app erpnext
fi
if [ "$WITH_APP" = "app" ] && ! bench --site "$NEW" list-apps | grep -qx ai_munimji; then
  step "install-app ai_munimji on $NEW" bench --site "$NEW" install-app ai_munimji
fi
step "tests allowed on $NEW" bench --site "$NEW" set-config allow_tests true
