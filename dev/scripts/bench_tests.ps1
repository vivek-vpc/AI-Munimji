# Runs a module of the app's tests on the test site and shows what matters: the verdict, and for each failing test its name and the last lines of its error (a development shortcut: the
# full gate is dev/gate.sh). The whole output is kept in $env:TEMP\bench_tests_last.txt.
#   .\dev\scripts\bench_tests.ps1 ai_munimji.tests.test_stores_contract [-Lines 3] [-Full]
param([Parameter(Mandatory = $true)][string]$Module, [int]$Lines = 3, [switch]$Full)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path (Split-Path -Parent $here) "exec.ps1"
$out = & $exec bash /workspace/ai_munimji/dev/run-tests.sh --module $Module 2>&1 | Out-String
$out | Set-Content -Encoding utf8 (Join-Path $env:TEMP "bench_tests_last.txt")
if ($Full) { $out; return }
$blocks = $out -split "(?m)^={60,}\r?$"
foreach ($b in $blocks) {
    if ($b -match "(?m)^\s*(ERROR|FAIL)\s+(\S+)") {
        $kind = $Matches[1]; $name = $Matches[2]
        $tail = ($b -split "\r?\n" | Where-Object { $_ -match "\S" -and $_ -notmatch "^\s{4,}" -and $_ -notmatch "^-{20,}" } | Select-Object -Last $Lines) -join " | "
        "$kind $name :: $($tail.Substring(0, [Math]::Min(500, $tail.Length)))"
    }
}
($out -split "\r?\n" | Where-Object { $_ -match "^(Ran |OK|FAILED|<== )" }) -join "`n"
