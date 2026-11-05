import frappe

from ai_munimji.install import ROLES

CUSTOM_FIELDS = ("Purchase Order-custom_agent_ref", "Purchase Order-custom_agent_approver")
PERMISSION_TYPES = ("munimji_approval_request_approve",)


def before_uninstall():
	"""Remove what the install added outside the app's own DocTypes (`bench uninstall-app` removes the DocTypes, the tables and the module itself).

	Left on purpose: the two COLUMNS on Purchase Order. Frappe never drops a column when a field is deleted, so that no data is lost
	(docs: "Database Migrations"); the columns hold the references of orders made from requests.
	"""
	# the cron entry of hooks.py became a Scheduled Job Type; without this it stays until the next `bench migrate`
	for name in frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ai_munimji.%"]}, pluck="name"):
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)

	for name in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

	# A Permission Type refuses to be deleted unless developer mode, install, migrate or a test run is on (permission_type.py: can_write),
	# which is not the case on a production site during `uninstall-app`. Its deletion also removes the "approve" column from the permission tables.
	previous = frappe.flags.in_migrate
	frappe.flags.in_migrate = True
	try:
		for name in PERMISSION_TYPES:
			if frappe.db.exists("Permission Type", name):
				frappe.delete_doc("Permission Type", name, force=True, ignore_permissions=True)
	finally:
		frappe.flags.in_migrate = previous

	for role in ROLES:
		frappe.db.delete("Has Role", {"role": role})
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, force=True, ignore_permissions=True)
