# Runs the repository's pre-commit hooks (ruff import sorter, ruff linter, ruff formatter, prettier, eslint, the file checks) on the files that are changed or new, inside the development
# container (which has uv). The linter workflow on GitHub runs the same hooks on every file, so a commit that passes this passes there.
#   .\dev\precommit.ps1            # the files git shows as changed or new
#   .\dev\precommit.ps1 -All       # every file
param([switch]$All)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
$root = Split-Path -Parent $here
if ($All) { $args2 = "--all-files" } else {
    $files = git -C $root status --short --untracked-files=all | ForEach-Object { $_.Substring(3).Trim().Trim('"') } | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $root $_)) -and $_ -notmatch "images\.lock$|\.ps1$|\.md$" }
    if (-not $files) { Write-Host "nothing to check"; exit 0 }
    $args2 = "--files " + ($files -join " ")
}
& $exec bash -c "cd /workspace/ai_munimji && uvx pre-commit run $args2 2>&1"
exit $LASTEXITCODE
