"""A writer for `ai_munimji_engine.testkit.loader` that works on the bench it runs in: Frappe documents made directly, no HTTP and no API key.

It has the methods of tools/testdata's REST `Writer` (the engine's `WriterLike`), so the world of the shared ERP-client checks is loaded by the same code whether it goes over
HTTP into any ERPNext or in process into this bench. Development tooling only: it runs as Administrator and reads with get_all, and it lives under dev/, not in the app.
"""

import json
from collections import Counter

import frappe


class InProcessWriter:
	dry_run = False

	def __init__(self):
		self.stats = Counter()

	def find(self, doctype, filters, fields=None, limit=1000):
		return [dict(r) for r in frappe.get_all(doctype, filters=filters, fields=fields or ["name"], limit_page_length=limit)]

	def get(self, doctype, name):
		return json.loads(frappe.as_json(frappe.get_doc(doctype, name).as_dict()))

	def ensure(self, doctype, name, doc):
		if frappe.db.exists(doctype, name):
			self.stats[f"{doctype}: existed"] += 1
			return "exists"
		self.create(doctype, doc)
		return "created"

	def ensure_one(self, doctype, filters, doc):
		if self.find(doctype, filters, limit=1):
			self.stats[f"{doctype}: existed"] += 1
			return "exists"
		self.create(doctype, doc)
		return "created"

	def create(self, doctype, doc):
		made = frappe.get_doc({**doc, "doctype": doctype}).insert()
		self.stats[f"{doctype}: created"] += 1
		return made.name

	def update(self, doctype, name, changes):
		doc = frappe.get_doc(doctype, name)
		doc.update(changes)
		doc.save()
		self.stats[f"{doctype}: updated"] += 1

	def submit(self, doctype, name):
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 0:
			doc.submit()
			self.stats[f"{doctype}: submitted"] += 1

	def call(self, method_path, **payload):
		result = frappe.call(frappe.get_attr(method_path), **payload)
		return json.loads(frappe.as_json(result.as_dict() if hasattr(result, "as_dict") else result))

	def summary(self):
		return "\n".join(f"  {k}: {v}" for k, v in sorted(self.stats.items())) or "  (nothing)"
