#!/usr/bin/env bash
# The one script that gets the engine (the package ai_munimji_engine, distribution ai-munimji-engine) into the bench. Until the engine is published, this installs a LOCAL wheel;
# once it is, pip finds it by the dependency line in pyproject.toml and this script is not needed. Nothing else in the repository knows how the engine arrives.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh                      # the newest wheel in dev/wheels/
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh <path to a .whl>     # that wheel
# Build the wheel first (it comes from the erpnext-ai-agents repository, never from PyPI):  .\dev\build-engine-wheel.ps1
# The environment already holds Frappe's pinned versions and the wheel needs pydantic and PyYAML only, so nothing but the wheel is installed (--no-deps).
# It has to run BEFORE the app is installed or updated: the app's dependency line makes the installer look for the engine, and it is found in the environment, not on PyPI.
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh

wheel="${1:-}"
if [ -z "$wheel" ]; then
  wheel=$(ls -t "$REPO"/dev/wheels/ai_munimji_engine-*.whl 2>/dev/null | head -1 || true)
fi
if [ -z "$wheel" ] || [ ! -f "$wheel" ]; then
  echo "No engine wheel found in $REPO/dev/wheels/. Build one on Windows with:  .\\dev\\build-engine-wheel.ps1" >&2
  exit 2
fi

py="$BENCH_DIR/env/bin/python"
echo "before: $("$py" -m pip list 2>/dev/null | grep -Ei '^(pydantic|pyyaml|ai-munimji-engine) ' | tr -s ' ' | paste -sd, - || true)"
# --force-reinstall: a rebuilt wheel keeps its version number, and pip would otherwise say "already satisfied" and keep the old files
if command -v uv >/dev/null 2>&1; then
  step "install the engine wheel with uv" uv pip install --python "$py" --no-deps --reinstall-package ai-munimji-engine "$wheel"
else
  step "install the engine wheel with pip" "$py" -m pip install --disable-pip-version-check --no-deps --force-reinstall "$wheel"
fi
"$py" -c "import ai_munimji_engine as e; print('installed: ai-munimji-engine', e.__version__, 'at', e.__file__)"
"$py" -m pip check
