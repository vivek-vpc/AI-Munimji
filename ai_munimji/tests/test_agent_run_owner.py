"""An Approver or a Manager may create an Agent Run (a request a person starts runs the procurement pass in their session), and only create it. A caller cannot put another user's name on the
row: a hand-made insert is refused whatever it says, and a run the stores make is owned by the person who is signed in.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji.stores import frappe_core_stores, frappe_stock_stores
from ai_munimji.tests.helpers import empty_store_tables, make_user

RUN = "Munimji Agent Run"


class TestAgentRunOwner(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"owner_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.approver = make_user("run.approver@example.com", ("Munimji Approver",))
		self.other = make_user("run.other@example.com", ("Munimji Manager",))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)

	def forged(self, name: str) -> dict:
		return {
			"doctype": RUN,
			"name": name,
			"owner": self.other,
			"modified_by": self.other,
			"agent": "procurement",
			"started_at": "2026-11-09 08:00:00",
			"dry_run": 0,
			"summary_json": json.dumps({"by": self.other}),
		}

	def test_a_hand_made_run_naming_another_user_is_refused(self):
		frappe.set_user(self.approver)
		for how in ("document", "client"):
			name = frappe.generate_hash(length=10)
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError), msg=how):
				if how == "document":
					frappe.get_doc(self.forged(name)).insert()
				else:
					frappe.client.insert(self.forged(name))
			frappe.set_user("Administrator")
			self.assertFalse(frappe.db.exists(RUN, name), f"{how}: nothing was made")
			frappe.set_user(self.approver)

	def test_a_run_the_stores_make_in_the_approvers_session_is_the_approvers_own(self):
		frappe.set_user(self.approver)
		stock = frappe_stock_stores(frappe_core_stores())
		run_id = frappe.generate_hash(length=10)
		stock.runs.add(
			run_id, "procurement", "2026-11-09T08:00:00+00:00", None, False, json.dumps({"by": self.other})
		)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value(RUN, run_id, ["owner", "modified_by"]), (self.approver, self.approver)
		)

	def test_the_approver_can_create_but_not_change_or_delete_a_run(self):
		stock = frappe_stock_stores(frappe_core_stores(system=True))
		run_id = frappe.generate_hash(length=10)
		stock.runs.add(run_id, "procurement", "2026-11-09T08:00:00+00:00", None, False, None)
		frappe.set_user(self.approver)
		self.assertTrue(frappe.has_permission(RUN, "create"))
		self.assertFalse(frappe.has_permission(RUN, "write"))
		self.assertFalse(frappe.has_permission(RUN, "delete"))
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value(RUN, run_id, "agent", "inventory")
		with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
			frappe.client.set_value(
				RUN, run_id, "owner", self.other
			)  # Frappe refuses a standard field as well
