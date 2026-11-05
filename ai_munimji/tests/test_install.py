import frappe

from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji.install import ROLES
from ai_munimji.uninstall import CUSTOM_FIELDS


class TestWhatTheInstallAdded(ERPNextTestSuite):
	def test_the_roles_exist(self):
		for role in ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_the_two_fields_are_on_purchase_order_and_the_reference_is_unique(self):
		for name in CUSTOM_FIELDS:
			self.assertTrue(frappe.db.exists("Custom Field", name), name)
		reference = frappe.get_meta("Purchase Order").get_field("custom_agent_ref")
		self.assertEqual((reference.fieldtype, reference.unique, reference.read_only), ("Data", 1, 1))
		self.assertEqual(frappe.get_meta("Purchase Order").get_field("custom_agent_approver").options, "User")

	def test_the_approve_permission_type_exists_for_the_doctype(self):
		self.assertEqual(frappe.db.get_value("Permission Type", "munimji_approval_request_approve", ["doc_type", "perm_type"]), ("Munimji Approval Request", "approve"))
