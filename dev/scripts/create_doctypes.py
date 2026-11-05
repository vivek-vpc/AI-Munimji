# ONE-OFF, already done: creates the roles, the two DocTypes and the "approve" permission type the way a developer does in the Desk
# (developer mode on), so that Frappe writes the DocType JSON and the controller files into the app. Kept as a record.
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/create_doctypes.py

MODULE = "AI Munimji"
ROLES = ["Munimji Viewer", "Munimji Approver", "Munimji Manager"]

# Every right is written out. The fields of a permission row (write, create, delete, share, print, email) DEFAULT TO 1, so a row made from
# {"role": ..., "read": 1} silently gives the role all of them. (Found in the first version of this script: the Viewer could write and delete.)
RIGHTS = ("read", "write", "create", "delete", "report", "export", "print", "email", "share")


def perm(role, *granted):
	return {"role": role, **{right: int(right in granted) for right in RIGHTS}}


if "reset" in args:  # start over: deleting a DocType in developer mode also deletes its files in the app
	# the Permission Type first: deleting it needs the DocType it belongs to ("Module None not found" otherwise)
	if frappe.db.exists("Permission Type", "munimji_approval_request_approve"):
		frappe.delete_doc("Permission Type", "munimji_approval_request_approve", force=1)
	for name in ("Munimji Approval Request", "AI Munimji Settings"):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=1)

for role in ROLES:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()

if not frappe.db.exists("DocType", "Munimji Approval Request"):
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": "Munimji Approval Request",
			"module": MODULE,
			"autoname": "format:MAR-{#####}",
			"track_changes": 1,
			"sort_field": "creation",
			"sort_order": "DESC",
			"fields": [
				{"fieldname": "item_code", "fieldtype": "Link", "options": "Item", "label": "Item", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
				{"fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "label": "Warehouse", "reqd": 1, "in_list_view": 1},
				{"fieldname": "qty", "fieldtype": "Float", "label": "Quantity", "reqd": 1, "non_negative": 1, "in_list_view": 1},
				{"fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "label": "Supplier"},
				{"fieldname": "reason", "fieldtype": "Small Text", "label": "Why this request exists"},
				{"fieldname": "column_break_status", "fieldtype": "Column Break"},
				{"fieldname": "status", "fieldtype": "Select", "options": "Pending\nOrdered\nRejected", "default": "Pending", "label": "Status", "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
				{"fieldname": "approved_by", "fieldtype": "Link", "options": "User", "label": "Approved by", "read_only": 1},
				{"fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "label": "Draft Purchase Order", "read_only": 1, "no_copy": 1},
			],
			"permissions": [
				perm("Munimji Viewer", "read", "report", "export"),
				perm("Munimji Approver", "read", "write", "report", "export"),
				perm("Munimji Manager", "read", "write", "create", "delete", "report", "export"),
				perm("System Manager", "read", "write", "create", "delete", "report", "export"),
			],
		}
	).insert()

if not frappe.db.exists("DocType", "AI Munimji Settings"):
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": "AI Munimji Settings",
			"module": MODULE,
			"issingle": 1,
			"track_changes": 1,
			"fields": [
				{"fieldname": "enabled", "fieldtype": "Check", "label": "Watch stock", "default": "1"},
				{"fieldname": "stock_threshold", "fieldtype": "Float", "label": "Ask for a purchase when the quantity in a warehouse is below", "default": "10", "non_negative": 1},
				{"fieldname": "fallback_supplier", "fieldtype": "Link", "options": "Supplier", "label": "Supplier to use when an item has none"},
				{"fieldname": "demo_secret", "fieldtype": "Password", "label": "A secret (spike: tests how a Password field is stored)"},
			],
			"permissions": [
				perm("Munimji Manager", "read", "write"),
				perm("System Manager", "read", "write"),
			],
		}
	).insert()

# the "approve" permission type (new in v16): the DocType must exist first, and the Permission Type adds an "approve" column to the permission rows
if not frappe.db.exists("Permission Type", "munimji_approval_request_approve"):
	frappe.get_doc({"doctype": "Permission Type", "doc_type": "Munimji Approval Request", "perm_type": "approve"}).insert()

doctype = frappe.get_doc("DocType", "Munimji Approval Request")
for row in doctype.permissions:
	if row.role in ("Munimji Approver", "Munimji Manager", "System Manager"):
		row.set("approve", 1)
doctype.save()
print("created:", frappe.get_all("DocType", filters={"module": MODULE}, pluck="name"))
