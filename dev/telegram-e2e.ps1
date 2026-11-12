# The whole way through Telegram, on real ERPNext data, without a bot, a token or the internet: starts a pretend Telegram (dev/scripts/fake_telegram.py) and a web server for ONE throw-away site in
# the development container, points that site at the pretend Telegram, and runs dev/scripts/telegram_e2e.py, which signs real people in over HTTP and walks a request from the stock check to a
# Draft Purchase Order by button presses.
#   .\dev\telegram-e2e.ps1                    # on the site world.localhost (ERPNext + the app + the contract world: .\dev\scripts\load_contract_world.py, after .\dev\scripts\seed.py)
#   .\dev\telegram-e2e.ps1 -Site other.localhost
#   .\dev\telegram-e2e.ps1 -Browser           # instead of the HTTP walk: the Telegram screens in the real Desk (dev/browser/telegram-ui.cjs) as a manager, an approver and a viewer; pictures in /tmp/telegram-shots in the container
#   .\dev\telegram-e2e.ps1 -Look              # leave the pretend Telegram and the site's server running afterwards (ports 8999 and 8010, in the container)
# The development bench must be running (.\dev\exec.ps1 bench start) with a worker started AFTER the app was last changed (a worker keeps the code it started with). The bench's own server on
# port 8000 serves the default site whatever the Host header says, which is why the site gets a server of its own, on port 8010: the development site is never touched.
param([string]$Site = "world.localhost", [switch]$Look, [switch]$Browser)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
$python = "/home/frappe/dev/frappe-bench/env/bin/python"

try { $up = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/api/method/ping" -TimeoutSec 8).StatusCode -eq 200 } catch { $up = $false }
if (-not $up) { Write-Host "The bench does not answer on http://localhost:8000. Start it:  .\dev\exec.ps1 bench start" -ForegroundColor Yellow; exit 2 }

function Stop-Pretend {
    # the brackets keep the pattern from matching the shell whose command line holds it
    & $exec bash -c "pkill -f '[f]ake_telegram.py'; pkill -f '[s]erve --port 8010'; true"
}

Stop-Pretend
Write-Host "Pointing $Site at the pretend Telegram (its own configuration: no page can do this) ..." -ForegroundColor Cyan
# first, and before its server starts: a server reads the configuration once, when it starts. The encryption key is made now too: a site gets one the first time a password is saved on it, and a
# server that is already running would then make a second one.
& $exec bash -c "cd /home/frappe/dev/frappe-bench && bench --site $Site execute frappe.utils.password.get_encryption_key > /dev/null"
& $exec bash -c "cd /home/frappe/dev/frappe-bench && bench --site $Site set-config ai_munimji_telegram_api_base http://127.0.0.1:8999 && bench --site $Site set-config host_name https://munimji-e2e.example.test"

Write-Host "Starting the pretend Telegram (port 8999) and a server for $Site (port 8010) ..." -ForegroundColor Cyan
& $exec bash -c "nohup $python /workspace/ai_munimji/dev/scripts/fake_telegram.py > /tmp/fake-telegram.log 2>&1 &"
& $exec bash -c "cd /home/frappe/dev/frappe-bench && nohup bench --site $Site serve --port 8010 --noreload > /tmp/serve-$Site.log 2>&1 &"
Start-Sleep -Seconds 8
& $exec bash -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8999/control/state | grep -q 200 && curl -s http://127.0.0.1:8010/api/method/ping | grep -q pong"
if ($LASTEXITCODE -ne 0) { Write-Host "The pretend Telegram or the site's server did not start (see /tmp/fake-telegram.log and /tmp/serve-$Site.log in the container)." -ForegroundColor Red; Stop-Pretend; exit 1 }

if ($Browser) {
    Write-Host "Making the people for the browser ..." -ForegroundColor Cyan
    & $exec bash -c "SITE=$Site bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/telegram_ui_setup.py"
    Write-Host "Running the check in the browser ..." -ForegroundColor Cyan
    & $exec bash -c "cd /workspace/ai_munimji/dev/browser && BASE=http://127.0.0.1:8010 FAKE=http://127.0.0.1:8999 node telegram-ui.cjs"
    $code = $LASTEXITCODE
    & $exec bash -c "SITE=$Site bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/telegram_ui_setup.py teardown"
} else {
    Write-Host "Running the check ..." -ForegroundColor Cyan
    & $exec bash -c "SITE=$Site bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/telegram_e2e.py"
    $code = $LASTEXITCODE
}

Write-Host "Putting the site back ..." -ForegroundColor Cyan
& $exec bash -c "cd /home/frappe/dev/frappe-bench && bench --site $Site set-config --parse ai_munimji_telegram_api_base None && bench --site $Site set-config --parse host_name None"
if (-not $Look) { Stop-Pretend }
exit $code
