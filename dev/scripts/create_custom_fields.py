# ONE-OFF, already done: adds the two fields this app puts on Purchase Order, the way a developer does (a Custom Field), so that
# `bench export-fixtures --app ai_munimji` can write them into the app. Run with:
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/create_custom_fields.py
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

create_custom_fields(
	{
		"Purchase Order": [
			{
				"fieldname": "custom_agent_ref",
				"label": "Munimji request",
				"fieldtype": "Data",
				"insert_after": "supplier",
				"read_only": 1,
				"unique": 1,
				"no_copy": 1,
				"description": "The Munimji Approval Request this order was made from. One request makes one order.",
			},
			{
				"fieldname": "custom_agent_approver",
				"label": "Approved by (Munimji)",
				"fieldtype": "Link",
				"options": "User",
				"insert_after": "custom_agent_ref",
				"read_only": 1,
				"no_copy": 1,
			},
		]
	}
)
print(frappe.get_all("Custom Field", filters={"dt": "Purchase Order", "fieldname": ["like", "custom_agent%"]}, pluck="name"))
