#!/usr/bin/env bash
# Runs this app's tests on the test site (never on the dev site: ERPNext's tests create their own test company and records).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-tests.sh [extra bench run-tests options, for example --module ai_munimji.tests.test_jobs]
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
TEST_SITE=${TEST_SITE:-test.localhost}
step "bench run-tests --app ai_munimji" bench --site "$TEST_SITE" run-tests --app ai_munimji "$@"
