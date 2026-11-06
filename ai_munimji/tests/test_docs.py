import unittest
from pathlib import Path

from ai_munimji.install import ROLES

DOCS = Path(__file__).resolve().parents[2] / "docs"


class TestTheInstallNotes(unittest.TestCase):
	def setUp(self):
		self.text = (DOCS / "INSTALL.md").read_text(encoding="utf-8")

	def test_they_name_the_munimji_roles_and_the_erpnext_roles_a_person_needs(self):
		for role in (*ROLES, "Stock User", "Purchase User", "Purchase Manager"):
			self.assertIn(role, self.text, f"docs/INSTALL.md does not name {role}")

	def test_they_say_the_app_adds_no_permission_rows_to_erpnext(self):
		self.assertIn("no permission rows to any ERPNext DocType", self.text)

	def test_they_do_not_claim_a_release(self):
		self.assertIn("not released", self.text)
		self.assertIn("not on the Frappe Marketplace", self.text)

	def test_they_say_which_versions_it_was_run_on(self):
		self.assertIn("Frappe 16.55.2 and ERPNext 16.53.0", self.text)
