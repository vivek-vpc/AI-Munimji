# Removes the AI Munimji development environment: its containers, its network and its two volumes (the bench and the database).
# Only the compose project "munimji-dev" is touched. The images stay on your machine (remove them with `docker image rm` if you want the space back).
# The source code in this folder is not touched.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$answer = Read-Host "Remove the containers, the network and the volumes of the project munimji-dev (the bench and its database)? Type yes"
if ($answer -ne "yes") { Write-Host "Nothing removed."; exit 0 }
docker compose -p munimji-dev -f (Join-Path $here "compose.yml") down --volumes --remove-orphans
