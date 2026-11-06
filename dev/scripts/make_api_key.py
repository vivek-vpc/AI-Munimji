# Makes (or renews) an API key and secret for Administrator on this site and writes them to dev/contract-key.json (not in git), for the REST client of the standalone service to
# read the dev site over HTTP in the contract table. Development tooling for the dev site only.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/make_api_key.py
import json
import os
from pathlib import Path

from frappe.core.doctype.user.user import generate_keys

secret = generate_keys("Administrator")["api_secret"]
key = frappe.db.get_value("User", "Administrator", "api_key")
Path(os.environ.get("MUNIMJI_REPO", "/workspace/ai_munimji"), "dev", "contract-key.json").write_text(json.dumps({"key": key, "secret": secret}), encoding="utf-8")
print("API key for Administrator written to dev/contract-key.json")
