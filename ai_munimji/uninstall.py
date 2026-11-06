import frappe
from frappe import _

from ai_munimji.custom_fields import NAMES as CUSTOM_FIELDS
from ai_munimji.install import ROLES

PERMISSION_TYPES = ("munimji_approval_request_approve",)


def what_stays() -> list[str]:
	"""What `bench uninstall-app ai_munimji` leaves behind, one sentence per line. The same lines are in docs/UNINSTALL.md (tests/test_uninstall.py compares them)."""
	return [
		_(
			"The database columns custom_agent_ref, custom_agent_approved_by and custom_agent_note on Purchase Order, Material Request and Stock Entry stay, with their values and the index on custom_agent_ref. Frappe never drops a column when a field is deleted, so that no data is lost."
		),
		_(
			"Every Purchase Order, Material Request and Stock Entry that was already made, drafts included, stays as it is. None is changed or deleted."
		),
		_(
			"The empty column approve stays in the tables DocPerm, Custom DocPerm and DocShare, where the permission type approve put it. Frappe does not drop it when the permission type is deleted, and it is shared by name with any other permission type called approve, so it is left alone. Installing again reuses it."
		),
		_(
			"The package ai-munimji-engine stays in the bench's Python environment. Remove it with: pip uninstall ai-munimji-engine"
		),
		_(
			"If the standalone service (erp-agents) also works on this site, it needs the seven fields that were just removed. Run erp-agents erp-setup again; it makes them again and finds the columns in place."
		),
	]


def before_uninstall():
	"""Remove what the install added outside the app's own DocTypes, then say what stays. `bench uninstall-app` itself removes the DocTypes (with their tables and every record in them,
	so the settings and the Munimji Approval Requests go), the module and the app entry.

	Left on purpose: the COLUMNS on Purchase Order, Material Request and Stock Entry. Frappe never drops a column when a field is deleted, so that no data is lost (docs: "Database
	Migrations"); the columns hold the references of orders made from requests.
	"""
	# the cron entry of hooks.py became a Scheduled Job Type; without this it stays until the next `bench migrate`
	# (the command line runs this as the system; frappe.db.get_values is the plain read, and frappe.get_all is kept for the scheduled job module: tests/test_rules.py)
	for name in frappe.db.get_values(
		"Scheduled Job Type", {"method": ["like", "ai_munimji.%"]}, "name", pluck=True
	):
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)

	for name in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

	# A Permission Type refuses to be deleted unless developer mode, install, migrate or a test run is on (permission_type.py: can_write),
	# which is not the case on a production site during `uninstall-app`. Deleting it does NOT drop the "approve" column that it added to the permission tables
	# (dev/check-uninstall.sh shows the column still there); it is not dropped here either, because a column is shared by name with any other permission type called approve.
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

	say(_("AI Munimji is being removed from this site."), what_stays())


def say(headline: str, lines: list[str]) -> None:
	"""To the terminal that runs `bench uninstall-app`, and to the message log for anything that runs the hook from the web."""
	print("\n".join([headline, *(f"- {line}" for line in lines)]))
	frappe.msgprint([headline, *lines], title=_("AI Munimji"), indicator="orange", as_list=True)
