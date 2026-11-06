# Stops the AI Munimji development containers and keeps their data (the bench, the database). Start again with .\dev\up.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
docker compose -p munimji-dev -f (Join-Path $here "compose.yml") stop
