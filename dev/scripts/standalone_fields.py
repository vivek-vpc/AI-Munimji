# Does what `erp-agents erp-setup` does on a site (ERPNextClient.ensure_po_reference_field in erpnext-ai-agents, commit 7f9bb9d): makes the seven Custom Fields of the standalone
# service when they are missing, with ITS labels and ITS body (read-only, not copied, hidden in print, the reference indexed), and says "created" or "exists".
# It stands in for the service in dev/check-uninstall.sh (scenario E): the service itself needs a running site and an API key, this needs neither.
#   env SITE=check.localhost bash dev/run-script.sh dev/scripts/standalone_fields.py
from ai_munimji.tests.test_custom_fields import STANDALONE

# the service's own labels and notes (erpnext.py: PO_REF_LABEL, PO_APPROVER_LABEL, MR_NOTE_LABEL)
LABELS = {"custom_agent_ref": "Agent proposal reference", "custom_agent_approved_by": "Approved by (Stock Assistant)", "custom_agent_note": "Stock Assistant note"}

made = False
for doctype, rows in STANDALONE.items():
	for fieldname, fieldtype, after, indexed in rows:
		if frappe.db.exists("Custom Field", f"{doctype}-{fieldname}"):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": doctype,
				"fieldname": fieldname,
				"label": LABELS[fieldname],
				"fieldtype": fieldtype,
				"insert_after": after,
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
				"search_index": indexed,
				"description": "Set by the Stock Assistant. Do not edit.",
			}
		).insert()
		made = True
frappe.clear_cache()
print("erp-setup:", "created" if made else "exists")
