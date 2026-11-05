#!/usr/bin/env bash
# Installs the engine wheel (built in the erpnext-ai-agents repository, never published) into the bench's own Python environment, from a local file, and says where it landed.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh /workspace/ai_munimji/dev/wheels/ai_munimji_engine-0.1.0-py3-none-any.whl
# The environment already holds Frappe's pinned versions; the wheel needs pydantic and PyYAML only, so pip installs nothing but the wheel (the output says so).
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
wheel="${1:?usage: install-engine.sh <path to ai_munimji_engine-*.whl>}"
py="$BENCH_DIR/env/bin/python"
echo "before: $("$py" -m pip list 2>/dev/null | grep -Ei '^(pydantic|pyyaml|ai-munimji-engine) ' | tr -s ' ' | paste -sd, - || true)"
if "$py" -m pip --version >/dev/null 2>&1; then
  step "install the engine wheel with pip" "$py" -m pip install --disable-pip-version-check "$wheel"
else
  step "install the engine wheel with uv" uv pip install --python "$py" "$wheel"
fi
"$py" -c "import ai_munimji_engine as e; print('installed: ai-munimji-engine', e.__version__, 'at', e.__file__)"
