# Who sees and answers what of the app's records, asked over HTTP as real signed-in people (list view, form, REST API, guessed names, changes, a person limited to one warehouse).
# The bench is started for the run and stopped after it, unless it is already running (verify-all runs this step while its bench is up).
#   .\dev\permissions-http.ps1
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
function Up { try { return (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/api/method/ping" -TimeoutSec 3).StatusCode -eq 200 } catch { return $false } }
$started = $false
if (-not (Up)) {
    docker exec -d -u frappe munimji-dev-frappe-1 bash -c "cd /home/frappe/dev/frappe-bench && exec bench start --no-dev > /home/frappe/dev/bench-start.log 2>&1"
    $started = $true
    for ($i = 0; $i -lt 60 -and -not (Up); $i++) { Start-Sleep -Seconds 2 }
    if (-not (Up)) { Write-Host "the site did not answer on http://localhost:8000 within two minutes" -ForegroundColor Red; exit 1 }
}
& $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/permissions_http.py
$code = $LASTEXITCODE
if ($started) { & $exec bash -c "pkill -INT -f 'honcho start'; sleep 4; pkill -f 'bench serve'; pkill -f 'frappe serve'; pkill -f socketio.js; pkill -f 'bench worker'; pkill -f 'bench schedule'; pkill -f 'esbuild --watch'; true" | Out-Null }
$global:LASTEXITCODE = $code
exit $code
