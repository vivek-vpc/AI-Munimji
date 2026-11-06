# Puts the demo back to "two requests waiting": deletes the DRAFT orders made from requests and the requests, then runs the stock job again.
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/reset_demo.py
from ai_munimji.jobs import check_stock

for name in frappe.get_all("Purchase Order", filters={"custom_agent_ref": ["is", "set"]}, pluck="name"):
	order = frappe.get_doc("Purchase Order", name)
	if order.docstatus != 0:
		print("left alone (not a draft):", name)
		continue
	frappe.delete_doc("Purchase Order", name, force=1, ignore_permissions=True)
	print("deleted draft order", name)

for name in frappe.get_all("Munimji Approval Request", pluck="name"):
	frappe.delete_doc("Munimji Approval Request", name, force=1, ignore_permissions=True)

print("requests created by the job:", check_stock())
