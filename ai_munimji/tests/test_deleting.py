"""The app's records name an Item, a Warehouse, a Supplier, a Purchase Order in Link fields, and none of them may stop ERPNext from deleting its own documents.

Frappe v16 has `ignore_links_on_delete` in hooks.py; hooks.py lists the app's DocTypes. A record keeps the name as text when what it names is deleted.
"""

from unittest import mock

import frappe
from frappe.model.delete_doc import check_if_doc_is_linked
from frappe.tests import IntegrationTestCase

from ai_munimji.stores import frappe_core_stores, frappe_stock_stores
from ai_munimji.tests.helpers import empty_store_tables, make_request

SETTINGS = "AI Munimji Settings"
NOW = "2026-11-09T08:00:00+00:00"


class TestDeleting(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"deleting_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)

	def a_proposal(self, item: str, supplier: str):
		stock = frappe_stock_stores(frappe_core_stores(system=True))
		proposal_id = frappe.generate_hash(length=10)
		stock.proposals.insert(
			proposal_id,
			"wo1",
			item,
			"awaiting",
			supplier,
			"A supplier",
			10.0,
			1.5,
			15.0,
			'{"vendors": []}',
			"",
			NOW,
		)
		return proposal_id, stock

	def make(self, doctype: str, **values):
		return frappe.get_doc({"doctype": doctype, **values}).insert()

	def test_the_hook_lists_every_doctype_of_the_app_but_the_settings_page(self):
		app = set(frappe.get_all("DocType", filters={"module": "AI Munimji"}, pluck="name")) - {SETTINGS}
		listed = {name for name in frappe.get_hooks("ignore_links_on_delete") if name.startswith("Munimji ")}
		self.assertEqual(listed, app)

	def test_an_item_with_a_proposal_can_be_deleted_and_the_proposal_keeps_its_text(self):
		code = f"ZZ-DEL-{frappe.generate_hash(length=6)}".upper()
		group = frappe.db.get_value("Item Group", {"is_group": 0}) or frappe.db.get_value("Item Group", {})
		item = self.make("Item", item_code=code, item_name=code, item_group=group, stock_uom="Nos")
		proposal_id, stock = self.a_proposal(code, "ZZ-NO-SUCH-SUPPLIER")
		frappe.delete_doc("Item", item.name)
		self.assertFalse(frappe.db.exists("Item", code), "the Item is gone")
		kept = stock.proposals.get(proposal_id)
		self.assertEqual(
			(kept["item_code"], kept["qty"], kept["total"]),
			(code, 10.0, 15.0),
			"the proposal keeps what it said",
		)

	def test_a_supplier_with_a_proposal_can_be_deleted(self):
		name = f"ZZ Supplier {frappe.generate_hash(length=6)}"
		group = (
			frappe.db.get_value("Supplier Group", {})
			or self.make(
				"Supplier Group", supplier_group_name="ZZ Group", parent_supplier_group="All Supplier Groups"
			).name
		)
		supplier = self.make("Supplier", supplier_name=name, supplier_group=group)
		proposal_id, stock = self.a_proposal("ZZ-ITEM", supplier.name)
		frappe.delete_doc("Supplier", supplier.name)
		self.assertFalse(frappe.db.exists("Supplier", supplier.name))
		self.assertEqual(stock.proposals.get(proposal_id)["supplier"], supplier.name)

	def test_a_warehouse_named_by_a_request_does_not_block_its_deletion_and_without_the_hook_it_would(self):
		make_request("Order bolts", warehouse="ZZ-GONE-WH")
		gone = frappe.get_doc({"doctype": "Warehouse", "name": "ZZ-GONE-WH"})
		check_if_doc_is_linked(gone)  # raises LinkExistsError if the request's Link to the Warehouse counted

		real = frappe.get_hooks

		def without_ours(hook=None, *args, **kwargs):
			return [] if hook == "ignore_links_on_delete" else real(hook, *args, **kwargs)

		with mock.patch.object(frappe, "get_hooks", without_ours):
			with self.assertRaises(frappe.LinkExistsError):
				check_if_doc_is_linked(gone)
