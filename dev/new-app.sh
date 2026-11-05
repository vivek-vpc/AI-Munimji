#!/usr/bin/env bash
# ONE-OFF, already done for this repository: makes the app skeleton with Frappe's own template (`bench new-app`), copies it into this
# repository, and links the repository into the bench the way bootstrap.sh does. Kept as a record of how the skeleton was made.
#   From Windows:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/new-app.sh
set -euo pipefail
source /workspace/ai_munimji/dev/lib.sh
cd "$BENCH_DIR"

if [ -f "$REPO/pyproject.toml" ]; then
  echo "This repository already holds the app; nothing to do."
  exit 0
fi

# the answers to the template's questions, in order: title, description, publisher, contact, licence, CI workflow (y/n), branch.
# The contact is a placeholder: replace it with the real publisher contact before anything is published.
answers() {
  printf '%s\n' \
    "AI Munimji" \
    "Stock monitoring and purchase requests for ERPNext (early spike, not released)" \
    "AI Munimji project" \
    "contact@example.com" \
    "gpl-3.0" \
    "y" \
    "main"
}

step "bench new-app ai_munimji (Frappe's template)" bash -c "$(declare -f answers); answers | bench new-app --no-git ai_munimji"
# -n: never overwrite a file this repository already has (README.md, .gitignore)
step "copy the skeleton into the repository" cp -an apps/ai_munimji/. "$REPO"/
step "remove the generated copy from the bench" bench remove-app ai_munimji --force --no-backup
step "get-app ai_munimji (soft link)" bench get-app --soft-link "$REPO"
step "install-app ai_munimji" bench --site "$SITE" install-app ai_munimji
