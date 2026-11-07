"""The base of every DocType that holds a row of the engine's stores.

These rows are the engine's own bookkeeping: a request, its answer, a proposal, an alert. The engine writes them through the stores, in the session of the person it acts for, and the
DocType's permission rows say who may do that. What the permission rows cannot say is "only the engine": a person who holds the right to write a request could otherwise change its status
or its answer with a plain API call (PUT /api/resource/...), or from the Desk's own edit, without the engine's rules and without the seal noticing until the next check. So a record is
saved or deleted only by a document the stores made: `flags.munimji_store`, set by `ai_munimji.stores.table` and `locks`, which a remote request cannot set. A script or console that wants
to do it must say so on purpose (`doc.flags.munimji_store = True`); the audit seal then still holds the history.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class StoreRecord(Document):
	def validate(self):
		self.only_through_the_stores()

	def on_trash(self):
		self.only_through_the_stores()

	def before_rename(self, old, new, merge=False):
		self.only_through_the_stores()

	def only_through_the_stores(self):
		if not self.flags.get("munimji_store"):
			frappe.throw(
				_(
					"This record is kept by the app's stores and is not edited by hand: use the screen's own buttons."
				),
				frappe.PermissionError,
			)
