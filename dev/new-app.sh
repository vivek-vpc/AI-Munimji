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
# The contact is the publisher's own address, chosen by the owner on 5 Nov 2026; it will be public.
answers() {
  printf '%s\n' \
    "AI Munimji" \
    "Watches stock and prepares draft purchase orders for approval" \
    "AI Munimji project" \
    "vivek.vpc1985@gmail.com" \
    "gpl-3.0" \
    "y" \
    "main"
}

step "bench new-app ai_munimji (Frappe's template)" bash -c "$(declare -f answers); answers | bench new-app --no-git ai_munimji"
# -n: never overwrite a file this repository already has (README.md, .gitignore). Not -a: preserving the time of the bind-mount root fails ("Operation not permitted").
step "copy the skeleton into the repository" cp -rn apps/ai_munimji/. "$REPO"/
step "remove the generated copy from the bench" bench remove-app ai_munimji --force --no-backup
# bootstrap.sh then soft-links the repository and installs the app on the site (every step of it is skipped when already done)
exec bash "$REPO/dev/bootstrap.sh"
