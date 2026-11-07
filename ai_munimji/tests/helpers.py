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


def empty_store_tables() -> None:
	"""Empty every DocType of the engine's stores, and the lock rows with them (the numbers start again at 1 and the lock rows are made again when needed). A test does this inside its own
	transaction and rolls back, so a site that holds records is not touched."""
	from ai_munimji.stores.specs import TABLES

	for table in TABLES:
		frappe.db.delete(table.doctype)
