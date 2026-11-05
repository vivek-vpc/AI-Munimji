#!/usr/bin/env bash
# The checks before a commit, inside the container: the app's tests, bandit, pip-audit. (Semgrep with Frappe's rules runs from Windows: dev\semgrep.ps1.)
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/gate.sh
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"
TOOLS=/home/frappe/dev/tools-venv

if [ ! -x "$TOOLS/bin/bandit" ]; then
  step "install bandit and pip-audit into $TOOLS" bash -c "python3 -m venv $TOOLS && $TOOLS/bin/pip install --quiet bandit pip-audit"
fi

bash "$REPO/dev/run-tests.sh"
step "bandit" "$TOOLS/bin/bandit" -r "$REPO/ai_munimji" -q -x "$REPO/ai_munimji/tests,$REPO/ai_munimji/ai_munimji/doctype/munimji_approval_request/test_munimji_approval_request.py,$REPO/ai_munimji/public"
step "pip-audit" "$TOOLS/bin/pip-audit" --desc on "$REPO"
