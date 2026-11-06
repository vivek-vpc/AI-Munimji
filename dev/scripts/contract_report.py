# Runs the shared ERP-client checks (ai_munimji_engine.testkit.contract) on the Frappe client, on the site this script runs on, which must hold the contract world
# (dev/scripts/load_contract_world.py). Prints one line per check and writes the results as JSON, for the table that sets the clients side by side
# (the standalone repository's tools/contract_table.py).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/contract_report.py <out.json> [who] [only,check,names]
# `who` is whose permissions the client has: Administrator (the default), a user's email, or one of the three people of docs/INSTALL.md, which this script makes and removes:
# viewer (Stock User), approver (Purchase User + Stock User), neither (a Munimji role only). The helpers that submit and remove the documents the write checks make act as Administrator.
import json
import os
from datetime import date
from pathlib import Path

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.helpers import make_user
from ai_munimji.tests.world import PEOPLE, discard, submit
from ai_munimji_engine.testkit import contract

out = Path(args[0] if args else "/tmp/contract-frappe.json")
who = args[1] if len(args) > 1 else "Administrator"
only = {n for n in args[2].split(",") if n} if len(args) > 2 else None
described = json.loads(Path(os.environ.get("MUNIMJI_REPO", "/workspace/ai_munimji"), "dev", "contract-site.json").read_text(encoding="utf-8"))

made = None
if who in PEOPLE:
	email, roles = PEOPLE[who]
	made = who = make_user(email, roles)

site = contract.Site(today=date.fromisoformat(described["today"]), names=described["names"], submit=submit, discard=discard)
try:
	frappe.set_user(who)
	results = contract.run_checks(FrappeERPClient(), site, only=only)
finally:
	frappe.set_user("Administrator")
	if made:
		frappe.delete_doc("User", made, force=True, ignore_permissions=True)
for r in results:
	print(f"{r.status.upper():5} {r.name}" + (f"\n        {r.detail}" if r.detail else ""))
print(f"\n{sum(r.status == 'pass' for r in results)} pass, {sum(r.status == 'fail' for r in results)} fail, {sum(r.status == 'error' for r in results)} error, {sum(r.status == 'skip' for r in results)} skip (as {who})")
out.write_text(json.dumps([r.__dict__ for r in results], indent=1), encoding="utf-8")
