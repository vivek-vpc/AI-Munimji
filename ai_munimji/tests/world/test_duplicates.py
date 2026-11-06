"""Two presses of one button make one document. `custom_agent_ref` is not unique in ERPNext (a cancelled order and its replacement share a reference, on purpose), so the client looks for
a not-cancelled document with the same reference before it makes one, and does so under a lock named for the reference.

A negative control in each test that matters takes the guard away and shows the test would have caught it. Nothing here is submitted by the client; the tests submit and cancel as Administrator
only to reach the state they want to look at."""

from unittest import mock

import frappe
from ai_munimji_engine.packs.stock_procurement.erp import (
	PurchaseOrderDraft,
	RequisitionDraft,
	StockTransferDraft,
)

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.world import WorldCase, as_administrator, as_user, submit

REF = "custom_agent_ref"


class TestOneDocumentPerReference(WorldCase):
	def reference(self, label: str) -> str:
		return f"WT-{label}-{frappe.generate_hash(length=6)}"

	def order(self, reference: str, qty: float = 3.0) -> PurchaseOrderDraft:
		return PurchaseOrderDraft(
			supplier=self.names["s1"],
			item_code=self.names["writes"],
			qty=qty,
			rate=12.0,
			uom="Nos",
			required_by=self.required_by(),
			reference=reference,
			approved_by="approver via desk",
		)

	def documents(self, doctype: str, reference: str, live_only: bool = False) -> list[dict]:
		with as_administrator():
			flt = {REF: reference, **({"docstatus": ["<", 2]} if live_only else {})}
			return frappe.get_all(
				doctype,
				filters=flt,
				fields=["name", "docstatus", "owner", "custom_agent_approved_by"],
				order_by="creation",
			)

	# ------------------------------------------------------------------ two presses give one order
	def test_two_presses_give_one_purchase_order(self):
		ref = self.reference("press")
		with as_user("approver"):
			client = FrappeERPClient()
			first, second = (
				client.create_purchase_order(self.order(ref)),
				client.create_purchase_order(self.order(ref)),
			)
		self.remember("Purchase Order", first.name)
		self.assertTrue(first.ok and second.ok, (first, second))
		self.assertEqual(first.name, second.name)
		rows = self.documents("Purchase Order", ref)
		self.assertEqual(
			[(r["name"], r["docstatus"], r["owner"]) for r in rows],
			[(first.name, 0, self.person("approver"))],
		)
		self.assertEqual(
			rows[0]["custom_agent_approved_by"], "approver via desk", "the approver is recorded on the draft"
		)

	def test_the_negative_control_without_the_guard_two_presses_make_two_orders(self):
		ref = self.reference("noguard")
		with as_user("approver"), mock.patch.object(FrappeERPClient, "find_by_reference", return_value=None):
			client = FrappeERPClient()
			first, second = (
				client.create_purchase_order(self.order(ref)),
				client.create_purchase_order(self.order(ref)),
			)
		self.remember("Purchase Order", first.name)
		self.remember("Purchase Order", second.name)
		self.assertNotEqual(first.name, second.name)
		self.assertEqual(
			len(self.documents("Purchase Order", ref, live_only=True)),
			2,
			"with the guard patched out, the same test would see two orders: it can fail",
		)

	def test_the_other_two_documents_are_guarded_in_the_same_way(self):
		requisition_ref, transfer_ref = self.reference("mr"), self.reference("st")
		with as_user("approver"):
			client = FrappeERPClient()
			mr = RequisitionDraft(
				item_code=self.names["writes"],
				qty=2,
				uom="Nos",
				required_by=self.required_by(9),
				reference=requisition_ref,
				approved_by="approver via desk",
			)
			st = StockTransferDraft(
				item_code=self.names["writes"],
				qty=1,
				uom="Nos",
				from_warehouse=self.names["wh_a"],
				to_warehouse=self.names["wh_b"],
				reference=transfer_ref,
				approved_by="approver via desk",
			)
			a, b = client.create_material_request(mr), client.create_material_request(mr)
			c, d = client.create_stock_transfer(st), client.create_stock_transfer(st)
		self.remember("Material Request", a.name)
		self.remember("Stock Entry", c.name)
		self.assertTrue(a.ok and b.ok and c.ok and d.ok, (a, b, c, d))
		self.assertEqual((a.name, c.name), (b.name, d.name))
		self.assertEqual([r["docstatus"] for r in self.documents("Material Request", requisition_ref)], [0])
		self.assertEqual(
			[r["docstatus"] for r in self.documents("Stock Entry", transfer_ref)],
			[0],
			"a transfer is a draft: it moves no stock until someone submits it",
		)

	def test_a_retry_after_the_order_was_changed_still_finds_it(self):
		ref = self.reference("retry")
		with as_user("approver"):
			client = FrappeERPClient()
			first = client.create_purchase_order(self.order(ref))
			self.remember("Purchase Order", first.name)
			client.update_purchase_order_qty(first.name, ref, self.names["writes"], 7.0)
			again = client.create_purchase_order(self.order(ref, qty=3.0))
		self.assertEqual(first.name, again.name)
		self.assertEqual(len(self.documents("Purchase Order", ref)), 1)

	# ------------------------------------------------------------------ a cancelled order and its replacement
	def test_a_cancelled_order_and_its_replacement_share_a_reference_and_the_replacement_is_accepted(self):
		ref = self.reference("replace")
		with as_user("approver"):
			client = FrappeERPClient()
			first = client.create_purchase_order(self.order(ref))
		self.remember("Purchase Order", first.name)
		submit("Purchase Order", first.name)
		with as_user("approver"):
			cancelled = client.cancel_purchase_order(first.name, ref)
			self.assertTrue(cancelled.ok, cancelled)
			self.assertIsNone(
				client.find_by_reference("Purchase Order", ref),
				"a cancelled order is not 'the order for this reference'",
			)
			second = client.create_purchase_order(self.order(ref, qty=5.0))
		self.remember("Purchase Order", second.name)
		self.assertTrue(second.ok, second)
		self.assertNotEqual(second.name, first.name)
		self.assertEqual(
			[(r["name"], r["docstatus"]) for r in self.documents("Purchase Order", ref)],
			[(first.name, 2), (second.name, 0)],
		)
		with as_user("approver"):
			self.assertEqual(client.find_by_reference("Purchase Order", ref).name, second.name)
			self.assertEqual(
				client.create_purchase_order(self.order(ref)).name,
				second.name,
				"and a third press finds the replacement",
			)

	# ------------------------------------------------------------------ an order made by hand
	def test_an_order_made_by_hand_with_no_reference_is_left_alone(self):
		ref = self.reference("hand")
		with as_user("approver"):
			hand = frappe.get_doc(
				{
					"doctype": "Purchase Order",
					"supplier": self.names["s1"],
					"company": self.company,
					"schedule_date": self.required_by().isoformat(),
					"items": [
						{
							"item_code": self.names["writes"],
							"qty": 2,
							"rate": 10,
							"schedule_date": self.required_by().isoformat(),
						}
					],
				}
			).insert()
			self.remember("Purchase Order", hand.name)
			client = FrappeERPClient()
			self.assertIsNone(
				client.find_by_reference("Purchase Order", ""),
				"an empty reference looks for nothing; it must not match the orders that have none",
			)
			self.assertIsNone(client.find_by_reference("Purchase Order", "   "))
			made = client.create_purchase_order(self.order(ref))
			self.remember("Purchase Order", made.name)
			self.assertNotEqual(made.name, hand.name)
			changed = client.update_purchase_order_qty(hand.name, ref, self.names["writes"], 9.0)
			cancelled = client.cancel_purchase_order(hand.name, ref)
			blank = client.cancel_purchase_order(hand.name, "")
		self.assertFalse(changed.ok or cancelled.ok or blank.ok, (changed, cancelled, blank))
		self.assertIn("left alone", changed.error + cancelled.error + blank.error)
		after = frappe.get_doc("Purchase Order", hand.name)
		self.assertEqual(
			(after.docstatus, after.items[0].qty, after.get(REF) or ""),
			(0, 2, ""),
			"the order made by hand is exactly as it was",
		)

	def test_an_order_for_another_reference_is_not_touched_by_this_one(self):
		ref, other = self.reference("mine"), self.reference("theirs")
		with as_user("approver"):
			client = FrappeERPClient()
			theirs = client.create_purchase_order(self.order(other))
			self.remember("Purchase Order", theirs.name)
			result = client.cancel_purchase_order(theirs.name, ref)
		self.assertFalse(result.ok)
		self.assertEqual(frappe.db.get_value("Purchase Order", theirs.name, "docstatus"), 0)

	# ------------------------------------------------------------------ nothing is made when the guard cannot be asked
	def test_a_person_who_may_not_read_orders_creates_nothing(self):
		ref = self.reference("blind")
		with as_user("neither"):
			result = FrappeERPClient().create_purchase_order(self.order(ref))
		self.assertFalse(result.ok)
		self.assertEqual(self.documents("Purchase Order", ref), [])
