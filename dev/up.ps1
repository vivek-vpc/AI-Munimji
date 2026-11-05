# Starts the AI Munimji development containers (docker compose project "munimji-dev"). Safe to run again.
#
# This is the one step that puts anything outside the project folder:
#   - it pulls two images: frappe/bench (about 0.9 GB download, pinned by digest in compose.yml) and redis:alpine;
#     mariadb:11.8 is used from your machine if it is already there;
#   - it creates one network and two named volumes (mariadb-data, bench) that belong to the project "munimji-dev".
# It does not touch any other Docker project (for example your ERPNext one). To remove everything it made: .\dev\destroy.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $here "compose.yml"

docker version --format "Docker server {{.Server.Version}}" | Write-Host
if ($LASTEXITCODE -ne 0) { throw "Docker does not answer. Start Docker Desktop and run this again." }

$clock = [Diagnostics.Stopwatch]::StartNew()
docker compose -p munimji-dev -f $compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed (exit code $LASTEXITCODE)" }
$clock.Stop()

$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Add-Content -Path (Join-Path $here "timings.log") -Value ("{0} | {1,-40} | {2,5} s | exit 0" -f $stamp, "docker compose up (pull + start)", [int]$clock.Elapsed.TotalSeconds)

# record which images were really used (digests), so the setup can be repeated exactly
$lock = Join-Path $here "images.lock"
$lines = @()
foreach ($image in @("docker.io/mariadb:11.8", "docker.io/redis:alpine")) {
    $digest = docker image inspect --format "{{index .RepoDigests 0}}" $image 2>$null
    $lines += ("{0}  {1}" -f $image, $digest)
}
$lines += "docker.io/frappe/bench  (pinned in compose.yml)"
Set-Content -Path $lock -Value $lines -Encoding ascii

docker compose -p munimji-dev -f $compose ps
Write-Host ""
Write-Host ("Done in {0} s. Next: tell Claude 'up', or run  .\dev\shell.ps1  to enter the development container." -f [int]$clock.Elapsed.TotalSeconds)
