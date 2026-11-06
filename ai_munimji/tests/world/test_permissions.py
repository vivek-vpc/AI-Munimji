"""Who gets data and who gets a permission error, method by method, for the three people docs/INSTALL.md speaks of:

* viewer    Stock User                        looks at stock and at what has been ordered
* approver  Purchase User + Stock User        answers a request, which makes a draft under their own login
* neither   Munimji Viewer only               an app role, which reads nothing of ERPNext's

The table is written out. A method that changes who it answers fails here until the table is changed on purpose. Every cell is also checked against what ERPNext itself says about that person
(`frappe.has_permission`), so the table cannot drift from ERPNext. The spike found `frappe.get_all` handing rows to a person who may not read them; two controls below show that this site does
that, and that none of the client's methods does."""

from datetime import timedelta

import frappe
from ai_munimji_engine.packs.stock_procurement.erp import (
	PurchaseOrderDraft,
	QuoteRule,
	RequisitionDraft,
	StockTransferDraft,
)

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.world import WorldCase, as_administrator, as_user, submit

DATA, DENIED = "data", "denied"
MADE, REFUSED = "made", "refused"

# method -> (the DocType whose read right it stands on, [viewer, approver, neither])
READS = {
	"healthcheck": (None, [DATA, DATA, DATA]),  # asks the site whether it is up; reads no business data
	"list_items": ("Item", [DATA, DATA, DENIED]),
	"list_warehouses": ("Warehouse", [DATA, DATA, DENIED]),
	"get_stock": ("Bin", [DATA, DATA, DENIED]),
	"get_consumption": ("Stock Ledger Entry", [DATA, DATA, DENIED]),
	"get_open_sales_orders": ("Sales Order Item", [DATA, DATA, DENIED]),
	"get_vendor_offers": ("Purchase Order", [DATA, DATA, DENIED]),
	"get_vendor_offers (with quotations)": ("Purchase Order", [DATA, DATA, DENIED]),
	"item_min_order_qty": ("Item", [DATA, DATA, DENIED]),
	"get_purchase_taxes": (
		"Tax Rule",
		[DENIED, DENIED, DENIED],
	),  # Accounts Manager only; the scheduled job reads them (test_taxes.py)
	"get_documents (Purchase Order)": ("Purchase Order", [DATA, DATA, DENIED]),
	"get_documents (Material Request)": ("Material Request", [DATA, DATA, DENIED]),
	"find_by_reference": ("Purchase Order", [DATA, DATA, DENIED]),
}
PEOPLE_ORDER = ["viewer", "approver", "neither"]
# what each person's roles allow them to MAKE (the app's request flow decides who may ask; ERPNext decides who may create)
WRITES = {
	"create_purchase_order": [REFUSED, MADE, REFUSED],  # Purchase User creates; Stock User does not
	"create_material_request": [MADE, MADE, REFUSED],  # Stock User may
	"create_stock_transfer": [MADE, MADE, REFUSED],
	"update_purchase_order_qty": [REFUSED, MADE, REFUSED],
	"cancel_purchase_order": [REFUSED, MADE, REFUSED],
}


class TestWhoGetsWhat(WorldCase):
	def reads(self) -> dict:
		n, today = self.names, self.today
		return {
			"healthcheck": lambda c: c.healthcheck(),
			"list_items": lambda c: c.list_items(),
			"list_warehouses": lambda c: c.list_warehouses(),
			"get_stock": lambda c: c.get_stock([n["steady"], n["low"]]),
			"get_consumption": lambda c: c.get_consumption([n["steady"]], today - timedelta(days=90), today),
			"get_open_sales_orders": lambda c: c.get_open_sales_orders(
				[n["steady"]], today + timedelta(days=30)
			),
			"get_vendor_offers": lambda c: c.get_vendor_offers(n["steady"], today - timedelta(days=180)),
			"get_vendor_offers (with quotations)": lambda c: c.get_vendor_offers(
				n["steady"], today - timedelta(days=180), QuoteRule(today)
			),
			"item_min_order_qty": lambda c: c.item_min_order_qty(n["moq"]),
			"get_purchase_taxes": lambda c: c.get_purchase_taxes(n["s1"], n["steady"], today),
			"get_documents (Purchase Order)": lambda c: c.get_documents(
				"Purchase Order", item_code=n["steady"], limit=50
			),
			"get_documents (Material Request)": lambda c: c.get_documents("Material Request", limit=50),
			"find_by_reference": lambda c: c.find_by_reference("Purchase Order", "CT-REF-O2"),
		}

	def outcome(self, user: str, call) -> str:
		with as_user(user):
			try:
				call(FrappeERPClient())
			except frappe.PermissionError:
				return DENIED
		return DATA

	# ------------------------------------------------------------------ reads
	def test_every_read_gives_data_or_a_permission_error_as_the_table_says(self):
		calls = self.reads()
		self.assertEqual(
			set(calls), set(READS), "a read was added or removed: the table above must say who gets it"
		)
		for method, (_doctype, expected) in READS.items():
			for key, want in zip(PEOPLE_ORDER, expected, strict=True):
				with self.subTest(method=method, person=key):
					self.assertEqual(self.outcome(key, calls[method]), want)

	def test_the_table_agrees_with_what_erpnext_says_about_each_person(self):
		for method, (doctype, expected) in READS.items():
			if doctype is None:
				continue
			for key, want in zip(PEOPLE_ORDER, expected, strict=True):
				with self.subTest(method=method, person=key):
					# the child tables of a document are read through the right on their parent
					parent = {"Sales Order Item": "Sales Order"}.get(doctype, doctype)
					readable = frappe.has_permission(parent, "read", user=self.person(key))
					self.assertEqual(
						readable,
						want == DATA,
						f"{key} {'may' if readable else 'may not'} read {parent}, so {method} should be {DATA if readable else DENIED}",
					)

	def test_administrator_gets_data_from_every_read(self):
		for method, call in self.reads().items():
			with self.subTest(method=method):
				self.assertEqual(self.outcome("Administrator", call), DATA)

	def test_the_message_says_who_may_not_read_what(self):
		with as_user("neither"), self.assertRaises(frappe.PermissionError) as caught:
			FrappeERPClient().list_items()
		self.assertIn(self.person("neither"), str(caught.exception))
		self.assertIn("Item", str(caught.exception))
		with as_user("approver"), self.assertRaises(frappe.PermissionError) as caught:
			FrappeERPClient().get_purchase_taxes(self.names["s1"], self.names["steady"], self.today)
		self.assertIn(
			"Tax Rule",
			str(caught.exception),
			"the engine shows this text when it tells the approver that taxes are not included",
		)

	# ------------------------------------------------------------------ nothing leaks
	def test_a_person_with_only_an_app_role_gets_not_one_row_from_any_read(self):
		results = {}
		for method, call in self.reads().items():
			with as_user("neither"):
				try:
					results[method] = call(FrappeERPClient())
				except frappe.PermissionError:
					continue
		self.assertEqual(
			{m: r for m, r in results.items() if m != "healthcheck"},
			{},
			"every read refuses: it returns no row, not an empty one",
		)

	def test_the_control_the_spikes_leak_exists_on_this_site_and_is_not_in_the_client(self):
		with as_user("neither"):
			leaked = frappe.get_all("Purchase Order", pluck="name", limit_page_length=5)
			self.assertTrue(
				leaked,
				"control: frappe.get_all hands purchase orders to a person who may not read them; this is the leak the app's rules forbid",
			)
			with self.assertRaises(frappe.PermissionError):
				FrappeERPClient().get_documents("Purchase Order")
			with self.assertRaises(frappe.PermissionError):
				FrappeERPClient().find_by_reference("Purchase Order", "CT-REF-O2")

	def test_a_person_who_has_only_the_select_right_on_item_gets_nothing(self):
		# frappe.get_list answers a person who has "select" but not "read" (the right that fills a link field's drop-down); the client asks for read first
		with as_user("neither"):
			opened = frappe.get_list("Item", fields=["name", "item_name"], limit_page_length=3)
			self.assertFalse(frappe.has_permission("Item", "read"))
			if not opened:
				self.skipTest(
					"this site does not open Item to the select right for this role, so the loophole is not there to close"
				)
			with self.assertRaises(frappe.PermissionError):
				FrappeERPClient().list_items()
			with self.assertRaises(frappe.PermissionError):
				FrappeERPClient().item_min_order_qty(self.names["moq"])

	def test_what_a_closed_doctype_would_add_is_not_in_what_a_viewer_gets(self):
		"""The Stock User sees stock and orders. The payment terms, the tax rule and the customer on a sales order are closed to them, and so they appear nowhere in what they get."""
		calls = self.reads()
		seen = []
		for call in calls.values():
			with as_user("viewer"):
				try:
					seen.append(repr(call(FrappeERPClient())))
				except frappe.PermissionError:
					pass
		everything = "\n".join(seen)
		with as_administrator():
			customer = frappe.db.get_value(
				"Sales Order", {"docstatus": 1, "company": self.company}, "customer"
			)
		self.assertNotIn("Import duty", everything)
		self.assertNotIn("Contract Duty", everything)
		if customer:
			self.assertNotIn(
				customer,
				everything,
				"the sales order's customer is not read: only the quantity and the date are",
			)
		offers = self.reads()["get_vendor_offers"]
		with as_user("viewer"):
			self.assertTrue(
				all(o.payment_days is None for o in offers(FrappeERPClient())),
				"payment terms are closed to a Stock User: the credit days are unknown, not guessed",
			)
		with as_user("approver"):
			self.assertTrue(any(o.payment_days for o in offers(FrappeERPClient())), "an approver reads them")

	# ------------------------------------------------------------------ writes
	def test_every_write_is_made_or_refused_as_the_table_says(self):
		n = self.names
		for index, key in enumerate(PEOPLE_ORDER):
			ref = f"WT-PERM-{key}-{frappe.generate_hash(length=6)}"
			order = PurchaseOrderDraft(
				supplier=n["s1"],
				item_code=n["writes"],
				qty=3,
				rate=12.0,
				uom="Nos",
				required_by=self.required_by(),
				reference=ref,
				approved_by=f"{key} via desk",
			)
			mine = PurchaseOrderDraft(
				supplier=n["s1"],
				item_code=n["writes"],
				qty=3,
				rate=12.0,
				uom="Nos",
				required_by=self.required_by(),
				reference=ref + "-mine",
				approved_by="approver via desk",
			)
			with as_user("approver"):
				theirs = FrappeERPClient().create_purchase_order(
					mine
				)  # an order an approver made, for the others to try to change
			self.remember("Purchase Order", theirs.name)
			requisition = RequisitionDraft(
				item_code=n["writes"],
				qty=2,
				uom="Nos",
				required_by=self.required_by(9),
				reference=ref + "-mr",
				approved_by=f"{key} via desk",
			)
			transfer = StockTransferDraft(
				item_code=n["writes"],
				qty=1,
				uom="Nos",
				from_warehouse=n["wh_a"],
				to_warehouse=n["wh_b"],
				reference=ref + "-st",
				approved_by=f"{key} via desk",
			)
			with as_user(key):
				c = FrappeERPClient()
				got = {
					"create_purchase_order": c.create_purchase_order(order),
					"create_material_request": c.create_material_request(requisition),
					"create_stock_transfer": c.create_stock_transfer(transfer),
					"update_purchase_order_qty": c.update_purchase_order_qty(
						theirs.name, ref + "-mine", n["writes"], 8.0
					),
				}
			for doctype, method in (
				("Purchase Order", "create_purchase_order"),
				("Material Request", "create_material_request"),
				("Stock Entry", "create_stock_transfer"),
			):
				if got[method].ok:
					self.remember(doctype, got[method].name)
			with as_user(
				key
			):  # cancelling comes last: for the approver it removes the draft that the update above changed
				got["cancel_purchase_order"] = FrappeERPClient().cancel_purchase_order(
					theirs.name, ref + "-mine"
				)
			for method, result in got.items():
				with self.subTest(method=method, person=key):
					self.assertEqual(
						MADE if result.ok else REFUSED, WRITES[method][index], f"{method} as {key}: {result}"
					)
			if key != "approver":
				self.assertTrue(
					frappe.db.exists("Purchase Order", theirs.name),
					f"{key} did not delete the approver's draft",
				)
				self.assertEqual(
					frappe.db.get_value("Purchase Order Item", {"parent": theirs.name}, "qty"),
					3,
					f"{key} did not change the approver's draft",
				)

	def test_nothing_is_ever_submitted_by_the_client(self):
		n = self.names
		ref = f"WT-DRAFT-{frappe.generate_hash(length=6)}"
		with as_user("approver"):
			made = FrappeERPClient().create_purchase_order(
				PurchaseOrderDraft(
					supplier=n["s1"],
					item_code=n["writes"],
					qty=3,
					rate=12.0,
					uom="Nos",
					required_by=self.required_by(),
					reference=ref,
					approved_by="approver via desk",
				)
			)
		self.remember("Purchase Order", made.name)
		self.assertEqual(frappe.db.get_value("Purchase Order", made.name, "docstatus"), 0)
		submit("Purchase Order", made.name)  # only a person does that, in ERPNext
		self.assertEqual(frappe.db.get_value("Purchase Order", made.name, "docstatus"), 1)
