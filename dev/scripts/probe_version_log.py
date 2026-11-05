# Probe: does a change to the Single DocType "AI Munimji Settings" write a Version record, and is a Password value left out of it?
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/probe_version_log.py
import json

print("track_changes on the DocType:", frappe.get_meta("AI Munimji Settings").track_changes)
settings = frappe.get_doc("AI Munimji Settings")
print("is_new():", settings.is_new(), "| has _doc_before_save before save:", hasattr(settings, "_doc_before_save"))
before = frappe.db.count("Version", {"ref_doctype": "AI Munimji Settings"})

settings.stock_threshold = (settings.stock_threshold or 0) + 1
settings.save()
print("_doc_before_save after save:", getattr(settings, "_doc_before_save", "missing"))

settings.demo_secret = "probe-secret-123"
settings.save()
rows = frappe.get_all("Version", filters={"ref_doctype": "AI Munimji Settings"}, fields=["name", "docname", "data"], order_by="creation")
print("versions before/after:", before, len(rows))
for row in rows[-3:]:
	print(row.name, row.docname, row.data)
print("secret appears in any version:", any("probe-secret-123" in (row.data or "") for row in rows))

# the same on an ordinary DocType, to compare
request = frappe.get_doc({"doctype": "Munimji Approval Request", "item_code": frappe.db.get_value("Item", {}, "name"), "warehouse": frappe.db.get_value("Warehouse", {"is_group": 0}, "name"), "qty": 1}).insert()
request.qty = 2
request.save()
print("versions for an ordinary DocType (after one change):", frappe.get_all("Version", filters={"ref_doctype": "Munimji Approval Request", "docname": request.name}, pluck="data"))
frappe.delete_doc("Munimji Approval Request", request.name, force=1)
