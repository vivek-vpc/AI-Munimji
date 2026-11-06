# PLACEHOLDER, replaced in Phase 5 together with ai_munimji/jobs.py (dev/README.md).
import frappe

from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji.jobs import check_stock

WAREHOUSE = "_Test Warehouse - _TC"


class TestCheckStock(ERPNextTestSuite):
	def setUp(self):
		settings = frappe.get_doc("AI Munimji Settings")
		settings.enabled = 1
		settings.min_qty = 10
		settings.save()
		self.item = make_item("_Munimji Test Item", {"is_stock_item": 1}).name

	def pending(self):
		return frappe.get_all(
			"Munimji Approval Request", filters={"item_code": self.item, "warehouse": WAREHOUSE, "status": "Pending"}, fields=["name", "qty", "reason"]
		)

	def test_a_warehouse_below_the_threshold_gets_one_pending_request_and_a_second_run_adds_none(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)

		check_stock()
		first = self.pending()
		self.assertEqual(len(first), 1)
		self.assertEqual(first[0].qty, 17, "enough to reach twice the threshold: 2 x 10 - 3")

		check_stock()
		self.assertEqual(self.pending(), first)

	def test_nothing_is_asked_for_when_the_stock_is_enough(self):
		make_stock_entry(item_code=self.item, qty=50, to_warehouse=WAREHOUSE, rate=10)
		check_stock()
		self.assertEqual(self.pending(), [])

	def test_stock_exactly_at_the_quantity_is_asked_for_and_zero_means_the_rule_is_not_used(self):
		make_stock_entry(item_code=self.item, qty=10, to_warehouse=WAREHOUSE, rate=10)
		check_stock()
		self.assertEqual([r.qty for r in self.pending()], [10], "at the quantity counts: 2 x 10 - 10")

		frappe.db.delete("Munimji Approval Request", {"item_code": self.item})
		settings = frappe.get_doc("AI Munimji Settings")
		settings.min_qty = 0
		settings.save()
		self.assertEqual(check_stock(), 0)
		self.assertEqual(self.pending(), [])

	def test_the_job_does_nothing_when_it_is_switched_off(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		settings = frappe.get_doc("AI Munimji Settings")
		settings.enabled = 0
		settings.save()
		self.assertEqual(check_stock(), 0)
		self.assertEqual(self.pending(), [])

	def test_the_job_only_writes_a_request_and_never_an_order(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		before = frappe.db.count("Purchase Order")
		check_stock()
		self.assertEqual(frappe.db.count("Purchase Order"), before)
		self.assertEqual(frappe.db.count("Material Request", {"creation": [">=", frappe.utils.add_to_date(None, minutes=-5)]}), 0)

	def test_the_schedule_is_registered_as_a_scheduled_job_type(self):
		jobs = frappe.get_all("Scheduled Job Type", filters={"method": "ai_munimji.jobs.check_stock"}, fields=["frequency", "cron_format", "stopped"])
		self.assertEqual([(j.frequency, j.cron_format, j.stopped) for j in jobs], [("Cron", "*/5 * * * *", 0)])
