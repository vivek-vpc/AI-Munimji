# Runs one command inside the development container as the user "frappe", in the bench directory (or in /home/frappe/dev before the bench exists):
#   .\dev\exec.ps1 bench version
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/bootstrap.sh
docker exec -u frappe munimji-dev-frappe-1 bash /workspace/ai_munimji/dev/in-bench.sh @args
exit $LASTEXITCODE
