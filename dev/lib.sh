#!/usr/bin/env bash
# Helpers for the dev scripts that run inside the container.
#   step "name" command args...   runs the command and appends how long it took to dev/timings.log (a file you can open on Windows too)

REPO=/workspace/ai_munimji
BENCH_DIR=/home/frappe/dev/frappe-bench
SITE=${SITE:-development.localhost}
TIMINGS=${TIMINGS:-$REPO/dev/timings.log}

step() {
  local name="$1"
  shift
  local start end rc=0
  start=$(date +%s)
  echo "==> $name"
  "$@" || rc=$?
  end=$(date +%s)
  printf '%s | %-40s | %5d s | exit %d\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" "$((end - start))" "$rc" >>"$TIMINGS"
  echo "<== $name: $((end - start)) s (exit $rc)"
  return "$rc"
}
