# Rebuilds the development environment from nothing and runs every check, printing how long each step took:
#   destroy (this project only) -> up -> bootstrap -> seed -> test site -> gate -> bench start -> round trip (HTTP) -> round trip (browser) -> uninstall check
#   .\dev\verify-all.ps1 -Fresh      # without -Fresh it keeps what exists and only runs the steps
# It removes the containers and volumes of the compose project "munimji-dev" ONLY when you pass -Fresh. Images stay on the machine.
param([switch]$Fresh)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
$results = New-Object System.Collections.ArrayList

function Step($name, [scriptblock]$body) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Write-Host "==> $name"
    $ok = $true
    try { & $body; if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { $ok = $false } } catch { $ok = $false; Write-Host $_.Exception.Message -ForegroundColor Red }
    $clock.Stop()
    [void]$results.Add([pscustomobject]@{ Step = $name; Seconds = [int]$clock.Elapsed.TotalSeconds; Result = $(if ($ok) { "ok" } else { "FAILED" }) })
    if (-not $ok) { Write-Host "<== $name FAILED" -ForegroundColor Red }
}

if ($Fresh) {
    Step "destroy the project munimji-dev (containers, volumes, network)" { docker compose -p munimji-dev -f (Join-Path $here "compose.yml") down --volumes --remove-orphans }
}
Step "up (images, containers)" { & (Join-Path $here "up.ps1") }
Step "bootstrap (bench init, ERPNext, dev site, app)" { & $exec bash /workspace/ai_munimji/dev/bootstrap.sh | Out-Host }
Step "seed the dev site" { & $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed.py | Out-Host }
Step "test site (ERPNext + app)" { & $exec bash /workspace/ai_munimji/dev/make-site.sh test.localhost app | Out-Host }
Step "gate: tests, bandit, pip-audit" { & $exec bash /workspace/ai_munimji/dev/gate.sh | Out-Host }
Step "bench start (background)" {
    docker exec -d -u frappe munimji-dev-frappe-1 bash -c "cd /home/frappe/dev/frappe-bench && exec bench start --no-dev > /home/frappe/dev/bench-start.log 2>&1"
    for ($i = 0; $i -lt 60; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/api/method/ping" -TimeoutSec 3).StatusCode -eq 200) { return } } catch { }; Start-Sleep -Seconds 2 }
    throw "the site did not answer on http://localhost:8000 within two minutes"
}
Step "make the demo: two waiting requests" { & $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/reset_demo.py | Out-Host }
Step "round trip over HTTP" { & (Join-Path $here "roundtrip.ps1") | Out-Host }
Step "put the demo back, then the round trip in a browser" {
    & $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/reset_demo.py | Out-Null
    & $exec bash -c "cd /workspace/ai_munimji/dev/browser && (test -d node_modules || npm ci --no-audit --no-fund) && node round-trip.cjs" | Out-Host
}
Step "stop bench" { & $exec bash -c "pkill -INT -f 'honcho start'; sleep 4; pkill -f 'bench serve'; pkill -f 'frappe serve'; pkill -f socketio.js; pkill -f 'bench worker'; pkill -f 'bench schedule'; pkill -f 'esbuild --watch'; true" | Out-Null; $global:LASTEXITCODE = 0 }
Step "uninstall check (throw-away site)" { & $exec bash /workspace/ai_munimji/dev/check-uninstall.sh | Out-Host }

Write-Host ""
$results | Format-Table -AutoSize | Out-String | Write-Host
$total = ($results | Measure-Object Seconds -Sum).Sum
Write-Host ("Total {0} s ({1:n1} min)" -f $total, ($total / 60))
if ($results | Where-Object { $_.Result -ne "ok" }) { exit 1 }
