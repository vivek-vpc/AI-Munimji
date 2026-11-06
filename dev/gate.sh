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

# The template of the translations must hold every word. It is made again with Frappe's own extractor and compared with the committed one; the dates in its header and the
# "#: file:line" comments (which move whenever a line moves) are not compared. If a message was added, removed or changed, the file is left rewritten and the gate fails: commit it.
POT="$REPO/ai_munimji/locale/main.pot"
cp "$POT" "$TOOLS/main.pot.before" 2>/dev/null || : >"$TOOLS/main.pot.before"
SITE=${TEST_SITE:-test.localhost} bash "$REPO/dev/run-script.sh" "$REPO/dev/scripts/make_pot.py" >/dev/null
if diff -q -I '^"POT-Creation-Date' -I '^"PO-Revision-Date' -I '^#: ' "$TOOLS/main.pot.before" "$POT" >/dev/null; then
  cp "$TOOLS/main.pot.before" "$POT"
  echo "main.pot: up to date"
else
  echo "main.pot was out of date and has been rewritten: review it and commit it" >&2
  exit 1
fi

step "bandit" "$TOOLS/bin/bandit" -r "$REPO/ai_munimji" -q -x "$REPO/ai_munimji/tests,$REPO/ai_munimji/ai_munimji/doctype/munimji_approval_request/test_munimji_approval_request.py,$REPO/ai_munimji/public"
# Not "pip-audit $REPO": the project's one dependency is the engine, which is not on PyPI, so the audit cannot resolve it (and before the engine line it audited nothing,
# because frappe is not listed). What the app adds to a bench is the engine and what the engine needs, so that installed set is audited; it must be clean.
"$BENCH_DIR/env/bin/python" "$REPO/dev/scripts/engine_requirements.py" >"$TOOLS/engine-requirements.txt"
echo "engine's runtime closure: $(paste -sd' ' "$TOOLS/engine-requirements.txt")"
step "pip-audit (the engine's dependencies, as installed)" "$TOOLS/bin/pip-audit" --desc on --no-deps --disable-pip -r "$TOOLS/engine-requirements.txt"
# Frappe's and ERPNext's own pins are not this app's to fix; they are listed for information and do not fail the gate.
"$BENCH_DIR/env/bin/python" -m pip freeze --exclude-editable 2>/dev/null | grep -Eiv '^(ai-munimji|ai_munimji)' >"$TOOLS/bench-requirements.txt" || true
step "pip-audit (the whole bench environment, information only)" bash -c "'$TOOLS/bin/pip-audit' --no-deps --disable-pip -r '$TOOLS/bench-requirements.txt' || true"
