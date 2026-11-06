# Runs the tests that need the contract world (items, suppliers, orders and a tax rule loaded by dev/scripts/load_contract_world.py) on the development site:
# the Frappe ERP client, as real users with real roles, on real data. The development containers must be up (.\dev\up.ps1).
#   .\dev\world-tests.ps1                                      # all of them
#   .\dev\world-tests.ps1 ai_munimji.tests.world.test_taxes    # one module
# -Load puts the world on the site first (safe to repeat: it finds what is there by its marker).
param([switch]$Load, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Modules)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
if ($Load) {
    & $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/load_contract_world.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/run_world_tests.py @Modules
exit $LASTEXITCODE
