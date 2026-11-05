import frappe

# README of the standalone service: to create a Purchase Order in ERPNext a person needs Purchase User AND Purchase Manager.
APPROVER_ROLES = ("Munimji Approver", "Purchase User", "Purchase Manager")


def make_user(email: str, roles: tuple[str, ...]) -> str:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": 1,
			"roles": [{"role": role} for role in roles],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


def make_request(**values):
	doc = frappe.get_doc(
		{
			"doctype": "Munimji Approval Request",
			"item_code": "_Test Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 10,
			"supplier": "_Test Supplier",
			"reason": "test",
			**values,
		}
	)
	return doc.insert()
