# Scans the whole history of this repository (every commit of every branch, not only the files of the latest one) for secrets, with gitleaks in a container pinned by digest. The repository
# is mounted read-only and nothing is sent anywhere. The rules are .gitleaks.toml (the default rules, plus one that fails the build if dev/contract-key.json is ever committed).
#   .\dev\secrets-scan.ps1
# CI runs the same command in the job "secrets" (.github/workflows/ci.yml). Exit code 0: no secret found.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$image = "ghcr.io/gitleaks/gitleaks@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9"  # gitleaks 8.30.0
docker run --rm -v "${repo}:/repo:ro" -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo $image git /repo --config /repo/.gitleaks.toml --log-opts="--all" --redact --no-banner
exit $LASTEXITCODE
