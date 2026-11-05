import frappe

ROLES = ("Munimji Viewer", "Munimji Approver", "Munimji Manager")


def before_install():
	"""Make the roles that the DocTypes' permission rows name. It runs before the DocTypes are synced, which is why it is not after_install."""
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
