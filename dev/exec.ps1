# Runs one command inside the development container, in the bench directory, as the user "frappe", for example:
#   .\dev\exec.ps1 bench version
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-tests.sh
docker exec -u frappe -w /home/frappe/dev/frappe-bench munimji-dev-frappe-1 @args
exit $LASTEXITCODE
