import re
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji import custom_fields, hooks, uninstall
from ai_munimji.install import ROLES

DOC = Path(__file__).resolve().parents[2] / "docs" / "UNINSTALL.md"


class TestTheUninstallStep(IntegrationTestCase):
	"""The step itself is run, on a throw-away site, by dev/check-uninstall.sh (it deletes roles and drops a column: not for a test site). These tests pin what can be pinned here."""

	def test_the_hook_is_wired(self):
		self.assertEqual(hooks.before_uninstall, "ai_munimji.uninstall.before_uninstall")
		self.assertEqual(frappe.get_attr(hooks.before_uninstall), uninstall.before_uninstall)

	def test_it_removes_what_the_install_added_outside_the_apps_own_doctypes(self):
		self.assertEqual(tuple(uninstall.CUSTOM_FIELDS), custom_fields.NAMES)
		self.assertEqual(uninstall.PERMISSION_TYPES, ("munimji_approval_request_approve",))
		self.assertEqual(tuple(ROLES), ("Munimji Viewer", "Munimji Approver", "Munimji Manager"))

	def test_what_it_says_stays_is_what_the_document_says(self):
		text = DOC.read_text(encoding="utf-8")
		for line in uninstall.what_stays():
			self.assertIn(
				f"- {line}", text, "docs/UNINSTALL.md must hold the text the uninstall prints, word for word"
			)
		self.assertEqual(len(uninstall.what_stays()), 5)

	def test_what_stays_names_the_things_that_do_stay(self):
		said = " ".join(uninstall.what_stays())
		for word in ("columns", "Purchase Order", "DocPerm", "ai-munimji-engine", "erp-agents erp-setup"):
			self.assertIn(word, said)

	def test_the_document_lists_everything_the_step_removes(self):
		text = DOC.read_text(encoding="utf-8")
		for thing in (
			*ROLES,
			"custom_agent_ref",
			"custom_agent_approved_by",
			"custom_agent_note",
			"approve",
			"scheduled job",
			"Dock",
			"Workspace",
			"AI Munimji Settings",
			"Munimji Approval Request",
			"Munimji Calendar Event",
		):
			self.assertIn(thing, text, thing)
		self.assertIsNone(re.search(r"small business|working prototype", text, re.I))
