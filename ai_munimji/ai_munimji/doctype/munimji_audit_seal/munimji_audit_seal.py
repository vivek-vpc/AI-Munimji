# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Two independent barriers keep the seal append only. The DocType's permission rows give no role the right to change or delete a row (even System Manager's row is read only), and this
# controller refuses a change or a delete from anyone who gets past the rows: Administrator, a call with ignore_permissions, a script. What it cannot stop is a write that does not go
# through a document at all (frappe.db.set_value, frappe.db.delete, SQL, `ignore_on_trash`): the chain itself detects those, because every entry holds the hash of the one before and
# a digest of the record it sealed (`AuditChain.verify`). A fork of the chain is refused by the unique index on `prev`.
APPEND_ONLY = "The audit seal is append only: a row is never changed or deleted."


class MunimjiAuditSeal(Document):
	"""One entry of the seal over the decision history: when, which record, what happened to it, a digest of the record as it was, the hash before and this entry's own."""

	def validate(self):
		self.refuse_to_change()

	def before_save(self):
		self.refuse_to_change()

	def on_trash(self):
		frappe.throw(_(APPEND_ONLY), frappe.PermissionError)

	def before_rename(self, old, new, merge=False):
		frappe.throw(_(APPEND_ONLY), frappe.PermissionError)

	def refuse_to_change(self):
		if not self.is_new():
			frappe.throw(_(APPEND_ONLY), frappe.PermissionError)
