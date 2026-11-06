# Builds the engine wheel from the erpnext-ai-agents repository into dev\wheels\ (not in git), the folder that dev/install-engine.sh reads. Nothing is published.
#   .\dev\build-engine-wheel.ps1                                   # the repository next to this one: ..\erpnext-ai-agents
#   .\dev\build-engine-wheel.ps1 -EngineRepo D:\code\erpnext-ai-agents
# The same command the engine's own wheel check starts with (tools/check_engine_wheel.py there, which also proves the wheel in a clean environment under Frappe's pins).
param([string]$EngineRepo = "")
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $EngineRepo) { $EngineRepo = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) "erpnext-ai-agents" }
$engine = Join-Path $EngineRepo "engine"
if (-not (Test-Path -LiteralPath (Join-Path $engine "pyproject.toml"))) { Write-Host "No engine/pyproject.toml in $EngineRepo. Pass -EngineRepo <the erpnext-ai-agents folder>." -ForegroundColor Red; exit 2 }
$python = Join-Path $EngineRepo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
$out = Join-Path $here "wheels"
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem -LiteralPath $out -Filter "ai_munimji_engine-*.whl" -ErrorAction SilentlyContinue | Remove-Item -Force
& $python -m pip wheel $engine --no-deps -w $out -q --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Write-Host "pip wheel failed" -ForegroundColor Red; exit 1 }
$built = Get-ChildItem -LiteralPath $out -Filter "ai_munimji_engine-*.whl"
if (@($built).Count -ne 1) { Write-Host "expected one wheel in $out, found $(@($built).Count)" -ForegroundColor Red; exit 1 }
$commit = (git -C $EngineRepo rev-parse --short HEAD) 2>$null
Write-Host ("built {0} ({1} KB) from {2} at commit {3}" -f $built.Name, [int]($built.Length / 1KB), $engine, $commit)
exit 0
