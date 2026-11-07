# Puts the demo back to "two purchase requests waiting": deletes the DRAFT orders made from requests, empties the app's records, then does what the stock job would after a person had
# approved two reorders: a work order for each of two items, and the procurement pass (in the job's system mode) that turns them into proposals and purchase requests.
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/reset_demo.py
from ai_munimji_engine.core.workorders import REORDER_NEEDED

from ai_munimji import jobs
from ai_munimji.tests.helpers import empty_store_tables

for name in frappe.get_all("Purchase Order", filters={"custom_agent_ref": ["is", "set"]}, pluck="name"):
	order = frappe.get_doc("Purchase Order", name)
	if order.docstatus != 0:
		print("left alone (not a draft):", name)
		continue
	frappe.delete_doc("Purchase Order", name, force=1, ignore_permissions=True)
	print("deleted draft order", name)

empty_store_tables()
services = jobs.system_services()
for code, qty in (("MD-BOLT-M8", 100), ("MD-WASHER-M8", 60)):
	services.workorders.emit(
		REORDER_NEEDED,
		{
			"item_code": code,
			"item_name": code,
			"item_group": "All Item Groups",
			"uom": "Nos",
			"suggested_qty": qty,
			"cover_days": 3.0,
			"lead_time_days": 7.0,
			"daily_rate": 1.0,
			"on_hand": 3.0,
			"severity": "HIGH",
			"reasons": ["Stock is low."],
		},
	)
report = services.procurement.run()
print(
	"purchase requests made:",
	report.proposed,
	"errors:",
	report.errors,
	"actions:",
	[(a["item_code"], a["action"]) for a in report.actions],
)
