import frappe

from ai_munimji.install import ROLES

APP_ROLES = frozenset(("System Manager", *ROLES))


def check_app_permission() -> bool:
	"""Whether the signed-in user is shown the AI Munimji tile on the apps screen: anyone with one of the app's roles, and the System Manager.
	Seeing the tile grants nothing: every page behind it checks the DocType's own permissions."""
	return bool(APP_ROLES.intersection(frappe.get_roles()))


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Hook for Munimji Approval Request. A controller hook can only deny: it cannot grant what the DocType's permission rows do not.

	Approving a request creates a Purchase Order, so it needs the right to create one in ERPNext, for the signed-in user.
	The keyword is `ptype`: Frappe v16 calls the hook with doc, ptype, user and debug (frappe/permissions.py: has_controller_permissions).
	The documentation's example names it `permission_type`, which Frappe would never fill in.
	"""
	if ptype == "approve" and not frappe.has_permission("Purchase Order", "create", user=user):
		return False
	return True
