#!/usr/bin/env bash
# Runs a Python file inside the development site (see frappe_run.py):  run-script.sh <script.py> [args...]
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR/sites"
exec "$BENCH_DIR/env/bin/python" "$REPO/dev/frappe_run.py" "$SITE" "$@"
