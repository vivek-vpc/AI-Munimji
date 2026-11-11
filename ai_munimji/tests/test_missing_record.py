"""A record that is not there is not announced to the person (found while following the flow of a request in the browser, Group 2).

Asking Frappe for a document that does not exist raises DoesNotExistError, which the stores catch and turn into "none", and ALSO puts "<DocType> <name> not found" among the messages the browser
shows with the reply. Approving a reorder reads the settings that may be set for the item, its group and its warehouse; most are not set; and the person saw a pop-up of five "Munimji Settings
Override ... not found" lines on top of the sentence that says what happens next.
"""

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.tests.test_vendor_comparison import FlowCase

OVERRIDE = "Munimji Settings Override"


class TestAMissingRecordSaysNothing(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.message_log = []

	def test_reading_a_record_that_is_not_there_leaves_the_browsers_messages_alone(self):
		table = frappe_core_stores().settings.o
		self.assertIsNone(table.get("no-such-override"))
		self.assertEqual(frappe.local.message_log, [])

	def test_changing_and_removing_one_that_is_not_there_do_the_same(self):
		table = frappe_core_stores().settings.o
		self.assertIsNone(table.change("no-such-override", lambda row: row))
		self.assertFalse(table.remove("no-such-override"))
		self.assertEqual(frappe.local.message_log, [])

	def test_the_lock_row_that_is_not_there_says_nothing_either(self):
		self.assertIsNone(locks._row("no-such-lock"))
		self.assertEqual(frappe.local.message_log, [])

	def test_a_message_that_was_there_before_is_kept(self):
		frappe.msgprint("Saved.")
		table = frappe_core_stores().settings.o
		table.get("no-such-override")
		self.assertEqual(len(frappe.local.message_log), 1, "the message of something else is not taken back")
		self.assertIn("Saved.", str(frappe.local.message_log[0]))

	def test_a_message_that_is_not_a_not_found_is_not_taken_back(self):
		table = frappe_core_stores().settings.o
		with mock.patch.object(frappe, "get_doc", side_effect=frappe.DoesNotExistError("gone")):
			frappe.msgprint("Something else happened.")
			table.get("x")
		self.assertEqual(len(frappe.local.message_log), 1)


class TestApprovingAReorderShowsNothingButTheSentence(FlowCase):
	def test_the_reply_carries_no_messages(self):
		request = self.raise_a_reorder()
		frappe.local.message_log = []
		self.answer(request, "approve")
		self.assertEqual(
			[m for m in frappe.local.message_log if "not found" in str(m)],
			[],
			"nothing is announced to the person but the sentence that says what happens next",
		)
