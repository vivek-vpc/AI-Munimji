#!/usr/bin/env bash
# Runs the given command in the bench directory, or in /home/frappe/dev before the bench exists (used by exec.ps1).
cd /home/frappe/dev/frappe-bench 2>/dev/null || cd /home/frappe/dev
exec "$@"
