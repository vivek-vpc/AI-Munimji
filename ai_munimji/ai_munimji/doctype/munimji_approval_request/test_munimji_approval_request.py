# Copyright (c) 2026, AI Munimji project and Contributors
# See license.txt

import frappe
from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji.tests.helpers import APPROVER_ROLES, make_request, make_user

REQUEST = "Munimji Approval Request"


class TestMunimjiApprovalRequest(ERPNextTestSuite):
	"""The request is the engine's approval record (ApprovalStore); what the engine does with an answer is tested with the engine's own services in tests/world/test_end_to_end.py. What is
	tested here is what belongs to the DocType: the `approve` right and its hook, and that a request made by a store reads back as the engine wrote it."""

	def setUp(self):
		self.viewer = make_user("munimji.viewer@example.com", ("Munimji Viewer",))
		self.approver_without_po_rights = make_user("munimji.nopo@example.com", ("Munimji Approver",))
		self.approver = make_user("munimji.approver@example.com", APPROVER_ROLES)

	def test_a_request_made_by_the_stores_has_the_columns_the_list_view_needs(self):
		request = make_request(
			title="Reorder bolts", item_code="_Test Item", qty=7, supplier="_Test Supplier"
		)
		self.assertEqual(
			(request.status, request.kind, request.title, request.item_code, request.qty, request.supplier),
			("pending", "procurement.po", "Reorder bolts", "_Test Item", 7, "_Test Supplier"),
		)
		self.assertEqual(frappe.parse_json(request.request_json)["title"], "Reorder bolts")

	def test_a_viewer_can_look_and_nothing_else(self):
		request = make_request()
		self.assertTrue(frappe.has_permission(request.doctype, "read", doc=request, user=self.viewer))
		for right in ("write", "create", "delete", "approve"):
			self.assertFalse(
				frappe.has_permission(request.doctype, right, doc=request, user=self.viewer), right
			)

	def test_the_approve_permission_needs_the_right_to_create_a_purchase_order(self):
		request = make_request()
		# the role has "approve", but ERPNext would not let this person create a Purchase Order, so the hook denies it
		self.assertFalse(
			frappe.has_permission(
				request.doctype, "approve", doc=request, user=self.approver_without_po_rights
			)
		)
		self.assertTrue(frappe.has_permission(request.doctype, "approve", doc=request, user=self.approver))

	def test_someone_who_may_create_orders_in_erpnext_but_has_no_role_of_the_app_is_refused(self):
		request = make_request()
		erpnext_only = make_user("munimji.erpnext.only@example.com", ("Purchase User", "Purchase Manager"))
		for right in ("read", "approve"):
			self.assertFalse(
				frappe.has_permission(request.doctype, right, doc=request, user=erpnext_only), right
			)

	def test_the_hook_only_denies_approve_and_takes_nothing_else_away(self):
		request = make_request()
		for right, expected in (
			("read", True),
			("write", True),
			("create", True),
			("delete", False),
			("approve", False),
		):
			self.assertEqual(
				frappe.has_permission(
					request.doctype, right, doc=request, user=self.approver_without_po_rights
				),
				expected,
				right,
			)

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

	def test_a_request_cannot_be_edited_by_hand_by_anyone_who_holds_the_right_to_write(self):
		request = make_request()
		with self.set_user(self.approver):
			doc = frappe.get_doc(REQUEST, request.name)
			doc.status = "decided"
			with self.assertRaises(frappe.PermissionError):
				doc.save()
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "status"), "pending")
