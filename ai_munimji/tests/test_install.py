import frappe

from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji.install import ROLES


class TestWhatTheInstallAdded(ERPNextTestSuite):
	def test_the_roles_exist(self):
		for role in ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_the_approve_permission_type_exists_for_the_doctype(self):
		self.assertEqual(frappe.db.get_value("Permission Type", "munimji_approval_request_approve", ["doc_type", "perm_type"]), ("Munimji Approval Request", "approve"))

	def test_the_settings_page_and_its_table_exist(self):
		self.assertEqual(frappe.db.get_value("DocType", "AI Munimji Settings", ["issingle", "module"]), (1, "AI Munimji"))
		self.assertEqual(frappe.db.get_value("DocType", "Munimji Calendar Event", ["istable", "module"]), (1, "AI Munimji"))
