"""Taxes, with the real client on a real site and the engine's real agent.

Reading Tax Rules needs the Accounts Manager role. A Purchase User, who makes the orders, does not have it. So:

1. the scheduled job (Administrator, the client's named system mode) reads the tax setup and the figures are kept with the request;
2. when a person changes the quantity, the recalculation uses the kept figures: it does not read the ERP again as that person;
3. when no tax figures are available at all, the request says plainly that taxes are not included. It never shows a zero as if it were a result.

In the world, one supplier ("s1", the reliable one) has a Tax Rule: 5% import duty on the net total, counted into the cost. The others have no rule and the site has no default template."""

from contextlib import contextmanager
from datetime import timedelta

import frappe

from ai_munimji import jobs
from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.world import WorldCase, as_administrator, as_user
from ai_munimji.tests.world.agent_kit import Kit


@contextmanager
def no_tax_rule_in_force(supplier: str, today):
	"""The supplier's Tax Rule ended three days ago, for as long as the block runs (the world's rule has no end date)."""
	with as_administrator():
		rules = frappe.get_all("Tax Rule", filters={"supplier": supplier, "tax_type": "Purchase"}, fields=["name", "to_date"])
		if not rules:
			raise AssertionError("the world has a Tax Rule for this supplier")
		for r in rules:
			frappe.db.set_value("Tax Rule", r.name, "to_date", today - timedelta(days=3))
	try:
		yield
	finally:
		with as_administrator():
			for r in rules:
				frappe.db.set_value("Tax Rule", r.name, "to_date", r.to_date)


def request_text(record) -> str:
	return " ".join(line for section in record.request.sections for line in section.lines)


class TestTaxFigures(WorldCase):
	def setUp(self):
		self.s1 = self.names["s1"]
		self.item = self.names["steady"]

	def job_proposal(self, qty: float = 100.0) -> tuple[Kit, object]:
		"""What the scheduled job does: a client in system mode, as Administrator, makes the request."""
		with as_administrator():
			kit = Kit(jobs.system_erp(), self.today)
			return kit, kit.propose(self.item, qty)

	# ------------------------------------------------------------------ 1. the job keeps the figures
	def test_the_job_reads_the_tax_rule_and_keeps_the_figures_with_the_request(self):
		kit, record = self.job_proposal()
		kept = kit.ranking()["tax_setups"]
		self.assertIn(self.s1, kept)
		self.assertEqual([(r["description"], r["charge_type"], r["rate"]) for r in kept[self.s1]["rows"]], [("Import duty", "On Net Total", 5.0)])
		vendor = kit.vendor(self.s1)
		self.assertGreater(vendor["tax_total"], 0)
		self.assertAlmostEqual(vendor["tax_total"], round(vendor["goods_total"] * 0.05, 2), places=2)
		self.assertNotIn("Taxes are not included", request_text(record))

	def test_the_system_mode_is_the_jobs_alone(self):
		for user in ("approver", "viewer", "neither"):
			with as_user(user), self.assertRaises(frappe.PermissionError, msg=user):
				FrappeERPClient(system=True)
		with as_administrator():
			client = jobs.system_erp()
			self.assertTrue(client.system)
		with as_user("approver"), self.assertRaises(frappe.PermissionError):
			client.get_purchase_taxes(self.s1, self.item, self.today)  # a system client that outlives the job's session refuses the next person who uses it

	def test_the_system_mode_reads_and_never_writes(self):
		from ai_munimji_engine.packs.stock_procurement.erp import PurchaseOrderDraft

		with as_administrator():
			result = jobs.system_erp().create_purchase_order(
				PurchaseOrderDraft(supplier=self.s1, item_code=self.names["writes"], qty=1, rate=1.0, uom="Nos", required_by=self.required_by(), reference="WT-SYSTEM-WRITE", approved_by="job")
			)
		self.assertFalse(result.ok)
		self.assertIn("scheduled job", result.error)
		self.assertEqual(frappe.db.count("Purchase Order", {"custom_agent_ref": "WT-SYSTEM-WRITE"}), 0)

	# ------------------------------------------------------------------ 2. a person's recalculation uses them
	def test_a_purchase_user_changing_the_quantity_gets_the_kept_figures_not_a_fresh_read(self):
		kit, record = self.job_proposal()
		with as_user("approver"):
			with self.assertRaises(frappe.PermissionError, msg="control: the same person cannot read the tax setup themselves"):
				FrappeERPClient().get_purchase_taxes(self.s1, self.item, self.today)
			kit.agent.erp = FrappeERPClient()  # the person's own client from here on
			result = kit.change_qty(record, 250)
		self.assertTrue(result.ok and result.status == "revised", result)
		vendor = kit.vendor(self.s1)
		self.assertEqual(vendor["goods_total"] * 0.05, vendor["tax_total"], "the duty is worked out for 250 from the kept rate")
		self.assertEqual(vendor["tax_template"], kit.ranking()["tax_setups"][self.s1]["template"])
		self.assertNotIn("Taxes are not included", request_text(result.approval))
		self.assertIn(self.s1, kit.ranking()["tax_setups"], "and the figures are still kept for the next change")

	def test_the_kept_figures_win_over_a_tax_rule_removed_afterwards(self):
		kit, record = self.job_proposal()
		with no_tax_rule_in_force(self.s1, self.today), as_administrator():
			kit.agent.erp = jobs.system_erp()  # even the job's own client, which could read the changed setup, is not asked again
			result = kit.change_qty(record, 250)
		self.assertTrue(result.ok, result)
		self.assertGreater(kit.vendor(self.s1)["tax_total"], 0, "the request keeps the figures it was made with, as the approver saw them")

	# ------------------------------------------------------------------ 3. no tax figures at all
	def test_a_request_made_by_a_person_who_cannot_read_tax_rules_says_taxes_are_not_included(self):
		with as_user("approver"):
			kit = Kit(FrappeERPClient(), self.today)
			record = kit.propose(self.item, 100)
		text = request_text(record)
		self.assertIn("Taxes are not included in these totals", text)
		self.assertIn("before tax", text)
		for supplier in (v["supplier"] for v in kit.ranking()["vendors"]):
			vendor = kit.vendor(supplier)
			self.assertEqual((vendor["tax_total"], vendor["tax_lines"]), (0.0, []), "no tax is shown")
			self.assertTrue(any("duties and taxes may be missing" in f for f in vendor["flags"]) or not vendor["eligible"], vendor["flags"])
		self.assertNotIn("tax_setups", kit.ranking(), "nothing was read, so nothing is kept")

	def test_changing_the_quantity_of_such_a_request_still_says_so(self):
		with as_user("approver"):
			kit = Kit(FrappeERPClient(), self.today)
			record = kit.propose(self.item, 100)
			result = kit.change_qty(record, 250)
		self.assertTrue(result.ok, result)
		self.assertIn("Taxes are not included in these totals", request_text(result.approval))

	def test_a_site_with_no_tax_rule_for_the_vendors_says_that_instead(self):
		with no_tax_rule_in_force(self.s1, self.today), as_administrator():  # only s1 sells the low item, and its Tax Rule has ended
			record = Kit(jobs.system_erp(), self.today).propose(self.names["low"], 30)
		text = request_text(record)
		self.assertIn("Duties and taxes are not in this comparison", text)
		self.assertNotIn("Taxes are not included in these totals", text, "the ERP was read and applies none: that is a different statement from 'could not read'")
