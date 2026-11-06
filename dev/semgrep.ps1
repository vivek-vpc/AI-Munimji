# Runs Frappe's Semgrep rules (github.com/frappe/semgrep-rules, MIT) over the app, the way the Marketplace's Audit Report and Frappe's own
# linter workflow do:  semgrep --config <rules>/rules --config r/python.lang.correctness <the app>
# Uses the semgrep/semgrep image if you already have it (it is not pulled here), and clones the rules into dev\.cache inside this folder (git-ignored).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$rules = Join-Path $here ".cache\frappe-semgrep-rules"
$commit = "81a6e3d47a328249e8ddf04c586e493dd5553002"   # the head of the rules on 5 Nov 2026

if (-not (docker image ls -q semgrep/semgrep:latest)) { throw "The image semgrep/semgrep:latest is not on this machine; pull it first (about 1.6 GB) if you want this check." }
if (-not (Test-Path $rules)) {
    New-Item -ItemType Directory -Force (Split-Path $rules) | Out-Null
    git clone --quiet https://github.com/frappe/semgrep-rules.git $rules
    git -C $rules checkout --quiet $commit
}
$clock = [Diagnostics.Stopwatch]::StartNew()
docker run --rm -v "${repo}:/src:ro" -v "${rules}:/rules:ro" semgrep/semgrep:latest `
    semgrep --metrics off --quiet --error --config /rules/rules --config r/python.lang.correctness --exclude dev --exclude .cache --exclude node_modules /src/ai_munimji
$code = $LASTEXITCODE
try {
    # the container writes to the same file through the bind mount; if it is busy right now the timing is only printed
    Add-Content -Path (Join-Path $here "timings.log") -Value ("{0} | {1,-40} | {2,5} s | exit {3}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"), "semgrep (Frappe rules + python.lang.correctness)", [int]$clock.Elapsed.TotalSeconds, $code)
} catch {
    Write-Host ("semgrep took {0} s (not written to timings.log: {1})" -f [int]$clock.Elapsed.TotalSeconds, $_.Exception.Message)
}
exit $code
