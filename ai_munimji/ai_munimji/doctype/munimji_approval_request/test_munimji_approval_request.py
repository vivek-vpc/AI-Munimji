# Copyright (c) 2026, AI Munimji project and Contributors
# See license.txt

import json

import frappe
from frappe.utils import add_days, nowdate

from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji.tests.helpers import APPROVER_ROLES, make_request, make_user


class TestMunimjiApprovalRequest(ERPNextTestSuite):
	def setUp(self):
		self.viewer = make_user("munimji.viewer@example.com", ("Munimji Viewer",))
		self.approver_without_po_rights = make_user("munimji.nopo@example.com", ("Munimji Approver",))
		self.approver = make_user("munimji.approver@example.com", APPROVER_ROLES)

	# --- who may do what

	def test_a_viewer_can_look_and_nothing_else(self):
		request = make_request()
		self.assertTrue(frappe.has_permission(request.doctype, "read", doc=request, user=self.viewer))
		for right in ("write", "create", "delete", "approve"):
			self.assertFalse(frappe.has_permission(request.doctype, right, doc=request, user=self.viewer), right)

	def test_the_permission_rows_grant_only_what_was_written(self):
		# the fields of a permission row default to 1; a row made from {"role": ..., "read": 1} gave the Viewer write, create and delete
		rights = ("read", "write", "create", "delete", "report", "export", "print", "email", "share", "approve")
		rows = {row.role: row for row in frappe.get_meta("Munimji Approval Request").permissions}
		granted = {role: [right for right in rights if row.get(right)] for role, row in rows.items()}
		self.assertEqual(granted["Munimji Viewer"], ["read", "report", "export"])
		self.assertEqual(granted["Munimji Approver"], ["read", "write", "report", "export", "approve"])
		self.assertNotIn("delete", granted["Munimji Approver"])

	def test_the_approve_permission_needs_the_right_to_create_a_purchase_order(self):
		request = make_request()
		# the role has "approve", but ERPNext would not let this person create a Purchase Order, so the hook denies it
		self.assertFalse(frappe.has_permission(request.doctype, "approve", doc=request, user=self.approver_without_po_rights))
		self.assertTrue(frappe.has_permission(request.doctype, "approve", doc=request, user=self.approver))

	def test_the_hook_documented_with_permission_type_is_never_given_it(self):
		# the documentation's example is `def has_permission(doc, user=None, permission_type=None)`; Frappe v16 calls hooks with `ptype`
		seen = {}

		def documented_hook(doc, user=None, permission_type=None):
			seen["permission_type"] = permission_type
			return True

		def working_hook(doc, ptype=None, user=None, debug=False):
			seen["ptype"] = ptype
			return True

		frappe.call(documented_hook, doc=object(), ptype="approve", user="x", debug=False)
		frappe.call(working_hook, doc=object(), ptype="approve", user="x", debug=False)
		self.assertIsNone(seen["permission_type"])
		self.assertEqual(seen["ptype"], "approve")

	# --- the round trip

	def test_an_approver_turns_a_request_into_a_draft_order_under_their_own_name(self):
		request = make_request(qty=7)
		with self.set_user(self.approver):
			order_name = frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()

		order = frappe.get_doc("Purchase Order", order_name)
		self.assertEqual(order.docstatus, 0, "a draft, never submitted")
		self.assertEqual(order.custom_agent_ref, request.name)
		self.assertEqual(order.custom_agent_approver, self.approver)
		self.assertEqual(order.owner, self.approver, "created by the signed-in user, not by a service account")
		self.assertEqual(order.company, frappe.db.get_value("Warehouse", request.warehouse, "company"))
		self.assertEqual((order.items[0].item_code, order.items[0].qty), ("_Test Item", 7))

		request.reload()
		self.assertEqual((request.status, request.approved_by, request.purchase_order), ("Ordered", self.approver, order_name))

	def test_a_second_order_for_the_same_request_is_refused(self):
		request = make_request()
		with self.set_user(self.approver):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertEqual(frappe.db.count("Purchase Order", {"custom_agent_ref": request.name}), 1)

	def test_the_database_refuses_a_second_order_with_the_same_reference_even_if_the_app_did_not(self):
		request = make_request()
		with self.set_user(self.approver):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()

		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		duplicate = create_purchase_order(do_not_save=True)
		duplicate.custom_agent_ref = request.name
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			duplicate.insert()

	def test_ordinary_orders_without_a_reference_are_not_blocked_by_the_unique_field(self):
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		first = create_purchase_order(do_not_submit=True)
		second = create_purchase_order(do_not_submit=True)
		self.assertNotEqual(first.name, second.name)
		self.assertFalse(first.custom_agent_ref or second.custom_agent_ref)

	def test_people_who_may_not_approve_get_no_order_and_no_half_done_request(self):
		request = make_request()
		for user in (self.viewer, self.approver_without_po_rights):
			with self.set_user(user), self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertEqual(frappe.db.get_value("Munimji Approval Request", request.name, "status"), "Pending")
		self.assertFalse(frappe.db.exists("Purchase Order", {"custom_agent_ref": request.name}))

	def test_someone_who_may_create_orders_in_erpnext_but_is_not_an_approver_here_is_refused(self):
		# ERPNext would let this person create the Purchase Order; it is this app's own "approve" permission that stops them
		buyer = make_user("munimji.buyer@example.com", ("Munimji Viewer", "Purchase User", "Purchase Manager"))
		request = make_request()
		with self.set_user(buyer), self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertFalse(frappe.db.exists("Purchase Order", {"custom_agent_ref": request.name}))

	def test_a_request_that_is_not_pending_is_refused_even_when_no_order_exists_yet(self):
		# the status check on its own: the order-exists check and the unique index cannot be what stops this one
		request = make_request()
		frappe.db.set_value("Munimji Approval Request", request.name, "status", "Rejected")
		with self.set_user(self.approver), self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertFalse(frappe.db.exists("Purchase Order", {"custom_agent_ref": request.name}))

	# --- the settings DocType and its Password field

	def test_a_password_field_is_kept_out_of_the_table_and_out_of_the_version_log(self):
		secret = "s3cret-value-for-the-test"
		settings = frappe.get_doc("AI Munimji Settings")
		settings.demo_secret = secret
		settings.save()
		self.assertEqual(frappe.get_doc("AI Munimji Settings").get_password("demo_secret"), secret)

		singles = frappe.db.sql("SELECT value FROM tabSingles WHERE doctype = 'AI Munimji Settings' AND field = 'demo_secret'")
		self.assertNotIn(secret, json.dumps(singles, default=str))
		stored = frappe.db.sql("SELECT password FROM `__Auth` WHERE doctype = 'AI Munimji Settings' AND name = 'AI Munimji Settings' AND fieldname = 'demo_secret'")
		self.assertTrue(stored)
		self.assertNotIn(secret, json.dumps(stored, default=str), "stored encrypted")

		# Document.save() sets ignore_version = frappe.in_test by default: the version log is OFF while tests run unless it is asked for
		settings.reload()
		settings.demo_secret = secret + "-changed"
		settings.stock_threshold = (settings.stock_threshold or 0) + 1
		settings.save(ignore_version=False)
		versions = frappe.get_all("Version", filters={"ref_doctype": "AI Munimji Settings"}, pluck="data")
		self.assertTrue(versions, "the version log records the change")
		changed = json.loads(versions[-1])["changed"]
		self.assertIn("demo_secret", [row[0] for row in changed], "the change of the Password field is recorded...")
		self.assertNotIn(secret, json.dumps(versions), "...but never its value")
