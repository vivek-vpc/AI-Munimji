"""Does changing or cancelling an order that was made from a request need more than Purchase User? Measured on ERPNext 16.54.0 (creating a draft also on 16.53.0), and pinned here, so that docs/INSTALL.md says only what is true.

Result: no. A Purchase User creates a draft, changes its quantity, deletes it; and on a submitted order changes the quantity (ERPNext's "Update Items") and cancels it. The Purchase Manager
role adds nothing to that. Purchase Manager is not a substitute for Purchase User either: on its own it cannot make the draft through the app, because the app first reads the supplier and the
company, which that role does not open."""

import frappe
from ai_munimji_engine.packs.stock_procurement.erp import PurchaseOrderDraft

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.helpers import make_user
from ai_munimji.tests.world import WorldCase, as_user, submit

ROLE_SETS = {
	"purchase_user": ("Purchase User",),
	"purchase_user_stock_user": ("Purchase User", "Stock User"),
	"purchase_user_manager": ("Purchase User", "Purchase Manager"),
	"purchase_manager_alone": ("Purchase Manager",),
}


class TestChangingAndCancellingAnOrderFromARequest(WorldCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for key, roles in ROLE_SETS.items():
			cls.users[key] = make_user(f"world.{key}@example.com".replace("_", "."), roles)

	def draft(self, ref: str) -> PurchaseOrderDraft:
		return PurchaseOrderDraft(
			supplier=self.names["s1"],
			item_code=self.names["writes"],
			qty=3,
			rate=12.0,
			uom="Nos",
			required_by=self.required_by(),
			reference=ref,
			approved_by="x via desk",
		)

	def test_a_purchase_user_is_enough_and_purchase_manager_adds_nothing(self):
		item = self.names["writes"]
		for key in ("purchase_user", "purchase_user_stock_user", "purchase_user_manager"):
			with self.subTest(roles=ROLE_SETS[key]):
				ref = f"WT-ROLE-{key}-{frappe.generate_hash(length=6)}"
				with as_user(self.person(key)):
					c = FrappeERPClient()
					made = c.create_purchase_order(self.draft(ref))
					self.assertTrue(made.ok, made)
					self.remember("Purchase Order", made.name)
					changed = c.update_purchase_order_qty(made.name, ref, item, 5.0)
					self.assertTrue(changed.ok and not changed.submitted, changed)
					self.assertEqual(
						frappe.db.get_value("Purchase Order Item", {"parent": made.name}, "qty"), 5
					)
					deleted = c.cancel_purchase_order(made.name, ref)
					self.assertTrue(deleted.ok and "deleted" in deleted.note, deleted)
					self.assertFalse(frappe.db.exists("Purchase Order", made.name))
					again = c.create_purchase_order(self.draft(ref + "-2"))
					self.remember("Purchase Order", again.name)
				submit("Purchase Order", again.name)
				with as_user(self.person(key)):
					changed = c.update_purchase_order_qty(again.name, ref + "-2", item, 6.0)
					self.assertTrue(changed.ok and changed.submitted, changed)
					self.assertEqual(
						frappe.db.get_value("Purchase Order Item", {"parent": again.name}, "qty"),
						6,
						"the submitted order was changed through Update Items",
					)
					cancelled = c.cancel_purchase_order(again.name, ref + "-2")
					self.assertTrue(cancelled.ok and "cancelled" in cancelled.note, cancelled)
					self.assertEqual(frappe.db.get_value("Purchase Order", again.name, "docstatus"), 2)

	def test_purchase_manager_alone_cannot_make_the_draft_through_the_app(self):
		ref = f"WT-ROLE-manager-{frappe.generate_hash(length=6)}"
		with as_user(self.person("purchase_manager_alone")):
			result = FrappeERPClient().create_purchase_order(self.draft(ref))
		self.assertFalse(result.ok, result)
		self.assertIn("may not read", result.error)
		self.assertFalse(
			frappe.db.exists("Purchase Order", {"custom_agent_ref": ref}), "and nothing was created"
		)
