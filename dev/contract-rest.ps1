# Runs the shared ERP-client checks on the standalone service's REST client, over HTTP, against this dev site (which must hold the contract world: dev/scripts/load_contract_world.py).
# The bench is started for the run and stopped after it. The standalone repository is the one next to this one (-EngineRepo to name another).
#   .\dev\contract-rest.ps1 [-Out dev\contract-rest.json]
param([string]$Out = "", [string]$EngineRepo = "")
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
if (-not $EngineRepo) { $EngineRepo = Join-Path (Split-Path -Parent $repo) "erpnext-ai-agents" }
if (-not $Out) { $Out = Join-Path $here "contract-rest.json" }
$exec = Join-Path $here "exec.ps1"
$python = Join-Path $EngineRepo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }

# the key first, then the bench: a site that has not used an encrypted field yet gets its encryption key written when the secret is made, and a bench started before that has not read it
& $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/make_api_key.py | Out-Null
$key = Get-Content -Raw (Join-Path $here "contract-key.json") | ConvertFrom-Json
docker exec -d -u frappe munimji-dev-frappe-1 bash -c "cd /home/frappe/dev/frappe-bench && exec bench start --no-dev > /home/frappe/dev/bench-start.log 2>&1"
$up = $false
for ($i = 0; $i -lt 60; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/api/method/ping" -TimeoutSec 3).StatusCode -eq 200) { $up = $true; break } } catch { }; Start-Sleep -Seconds 2 }
if (-not $up) { Write-Host "the site did not answer on http://localhost:8000 within two minutes" -ForegroundColor Red; exit 1 }
Push-Location $EngineRepo
& $python tools/contract_report.py rest --site (Join-Path $here "contract-site.json") --url http://localhost:8000 --key $key.key --secret $key.secret --out $Out
$code = $LASTEXITCODE
Pop-Location
& $exec bash -c "pkill -INT -f 'honcho start'; sleep 4; pkill -f 'bench serve'; pkill -f 'frappe serve'; pkill -f socketio.js; pkill -f 'bench worker'; pkill -f 'bench schedule'; pkill -f 'esbuild --watch'; true" | Out-Null
$global:LASTEXITCODE = $code
exit $code
