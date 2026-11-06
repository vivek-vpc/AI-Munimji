# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, nowdate


class MunimjiApprovalRequest(Document):
	def validate(self):
		if (self.qty or 0) <= 0:
			frappe.throw(_("The quantity must be more than zero."))

	@frappe.whitelist(methods=["POST"])
	def create_draft_purchase_order(self) -> str:
		"""The one thing a person can do with a request: turn it into a DRAFT Purchase Order, under their own ERPNext login.

		Nothing is submitted. ERPNext checks the signed-in user's own rights on Purchase Order when the document is inserted, because this does not
		pass ignore_permissions. The order carries the request's name in custom_agent_ref and the approver in custom_agent_approved_by ("user via desk"), the same two fields
		(and the same form of words) that the standalone service writes, so that either product recognises the other's orders (ai_munimji/custom_fields.py).
		A request becomes an order once: the row is locked until this transaction ends, so a second click waits and then sees "Ordered".

		PLACEHOLDER, replaced in Phase 5: the request, this method and the button that calls it are the spike's, kept so that the app can be tried end to end.
		"""
		self.check_permission("approve")

		# SELECT ... FOR UPDATE: a concurrent second call blocks here until the first commits, then reads the new status
		status = frappe.db.get_value(self.doctype, self.name, "status", for_update=True)
		if status != "Pending":
			frappe.throw(_("This request is already {0}; it cannot be turned into an order again.").format(status))
		# the same question the standalone asks: a cancelled order does not count, so that a request whose order was cancelled can be answered again
		if frappe.db.exists("Purchase Order", {"custom_agent_ref": self.name, "docstatus": ["<", 2]}):
			frappe.throw(_("A Purchase Order for this request already exists."))

		supplier = self.supplier or frappe.db.get_single_value("AI Munimji Settings", "fallback_supplier")
		if not supplier:
			frappe.throw(_("Choose a supplier on the request, or set a fallback supplier in AI Munimji Settings."))

		po = frappe.new_doc("Purchase Order")
		po.company = frappe.db.get_value("Warehouse", self.warehouse, "company")  # a warehouse belongs to one company: no guessing from user defaults
		po.supplier = supplier
		po.transaction_date = nowdate()
		po.schedule_date = add_days(nowdate(), 7)
		po.custom_agent_ref = self.name
		po.custom_agent_approved_by = f"{frappe.session.user} via desk"[:140]
		po.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": self.qty,
				"warehouse": self.warehouse,
				"schedule_date": po.schedule_date,
				"rate": _last_rate(self.item_code),
			},
		)
		po.set_missing_values()
		po.insert()  # as the signed-in user: no ignore_permissions

		self.status = "Ordered"
		self.approved_by = frappe.session.user
		self.purchase_order = po.name
		self.save()
		return po.name


def _last_rate(item_code: str) -> float:
	last_purchase_rate, standard_rate = frappe.db.get_value("Item", item_code, ["last_purchase_rate", "standard_rate"]) or (0, 0)
	return last_purchase_rate or standard_rate or 0
