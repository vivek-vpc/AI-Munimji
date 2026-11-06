# PLACEHOLDER, replaced in Phase 5 together with the Munimji Approval Request DocType and its button (dev/README.md). The tests of who may approve (the hook) stay in some form.
# Copyright (c) 2026, AI Munimji project and Contributors
# See license.txt

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
		self.assertEqual(order.custom_agent_approved_by, f"{self.approver} via desk", "the form of words the standalone service writes: user, 'via', where from")
		self.assertEqual(order.owner, self.approver, "created by the signed-in user, not by a service account")
		self.assertEqual(order.company, frappe.db.get_value("Warehouse", request.warehouse, "company"))
		self.assertEqual((order.items[0].item_code, order.items[0].qty), ("_Test Item", 7))

		request.reload()
		self.assertEqual((request.status, request.approved_by, request.purchase_order), ("Ordered", self.approver, order_name))

	def test_purchase_user_without_purchase_manager_is_enough_to_make_the_draft(self):
		# measured on ERPNext 16.53.0 (docs/INSTALL.md): the standalone service's README asks for both roles, the whole round trip here needs only Purchase User and Stock User
		approver = make_user("munimji.approver.pu@example.com", ("Munimji Approver", "Purchase User", "Stock User"))
		request = make_request()
		with self.set_user(approver):
			order = frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertEqual(frappe.db.get_value("Purchase Order", order, "docstatus"), 0)

	def test_a_second_order_for_the_same_request_is_refused(self):
		request = make_request()
		with self.set_user(self.approver):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertEqual(frappe.db.count("Purchase Order", {"custom_agent_ref": request.name}), 1)

	def test_a_request_with_a_live_order_is_refused_even_if_it_shows_pending(self):
		# the guard on its own: the status check cannot be what stops this one, and the reference is not unique in the database (next test)
		request = make_request()
		with self.set_user(self.approver):
			frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
			frappe.db.set_value("Munimji Approval Request", request.name, "status", "Pending")
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc("Munimji Approval Request", request.name).create_draft_purchase_order()
		self.assertEqual(frappe.db.count("Purchase Order", {"custom_agent_ref": request.name}), 1)

	def test_a_cancelled_order_and_its_replacement_may_carry_the_same_reference(self):
		# The standalone service does exactly this when an order is changed: it looks for the order of a reference with docstatus < 2, so the reference cannot be unique.
		# (The spike made it unique; a replacement would have been refused by the database.)
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		first = create_purchase_order(do_not_save=True)
		first.custom_agent_ref = "MAR-REORDER-1"
		first.insert()
		first.submit()
		first.cancel()
		second = create_purchase_order(do_not_save=True)
		second.custom_agent_ref = "MAR-REORDER-1"
		second.insert()
		live = frappe.get_all("Purchase Order", filters={"custom_agent_ref": "MAR-REORDER-1", "docstatus": ["<", 2]}, pluck="name")
		self.assertEqual(live, [second.name])
		self.assertEqual(frappe.db.count("Purchase Order", {"custom_agent_ref": "MAR-REORDER-1"}), 2)

	def test_ordinary_orders_without_a_reference_are_not_affected_by_the_field(self):
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
