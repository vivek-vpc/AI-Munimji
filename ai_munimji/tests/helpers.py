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


def make_request(title: str = "Reorder", **facts):
	"""A pending purchase request, made as the engine makes one (through the approval store, in the named system mode: run it as Administrator). `facts` are the request's facts."""
	import json

	from ai_munimji.stores import frappe_core_stores

	request = {
		"kind": "procurement.po",
		"title": title,
		"facts": {
			"item_code": "_Test Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 10,
			"supplier": "_Test Supplier",
			**facts,
		},
	}
	request_id = frappe.generate_hash(length=10)
	frappe_core_stores(system=True).approvals.insert(
		request_id,
		"procurement.po",
		json.dumps(request),
		"procurement_proposal",
		request_id,
		"2026-10-16T08:00:00+00:00",
		None,
	)
	return frappe.get_doc("Munimji Approval Request", request_id)


def empty_store_tables() -> None:
	"""Empty every DocType of the engine's stores, then make the lock rows again (the numbers start again at 1). A test does this inside its own transaction and rolls back, so a site that
	holds records is not touched; one that commits (the parallel and end-to-end tests) empties the tables again when it is done."""
	from ai_munimji.stores import locks
	from ai_munimji.stores.specs import TABLES

	for table in TABLES:
		frappe.db.delete(table.doctype)
	locks.ensure()
