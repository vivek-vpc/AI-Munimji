from unittest import mock

import frappe
from ai_munimji_engine.packs.stock_procurement.inventory import agent as agent_module
from ai_munimji_engine.packs.stock_procurement.inventory.agent import InventoryAgent
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND as KIND_REORDER
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.tests.utils import ERPNextTestSuite

from ai_munimji import jobs, last_run
from ai_munimji.jobs import check_stock, run_stock_check
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.tests.helpers import empty_store_tables, make_user

WAREHOUSE = "_Test Warehouse - _TC"
REQUEST = "Munimji Approval Request"


def free_lease():
	"""The lease commits what is pending, and these tests have pending writes (their item, their stock entry); the lease itself is tested below and in world/test_end_to_end.py."""
	return mock.patch.multiple(
		locks, lease=mock.Mock(return_value=True), release=mock.Mock(return_value=None)
	)


class TestTheStockCheck(ERPNextTestSuite):
	def setUp(self):
		empty_store_tables()
		settings = frappe.get_doc("AI Munimji Settings")
		settings.enabled = 1
		settings.min_qty = 10
		settings.min_days_cover = 0
		settings.stock_alerts = 0  # a request, not an information-only notice first
		settings.save()
		# a new item for every test: a test site keeps what earlier runs committed, and the stock of an item is what the rules look at
		self.item = make_item(
			f"_Munimji Test Item {frappe.generate_hash(length=6)}", {"is_stock_item": 1}
		).name

	def requests(self):
		return frappe.get_all(
			REQUEST, filters={"item_code": self.item}, fields=["name", "kind", "status", "warehouse", "qty"]
		)

	def test_an_item_at_or_below_the_quantity_gets_one_request_to_start_a_reorder_and_a_second_run_adds_none(
		self,
	):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		with free_lease():
			first = run_stock_check(items=[self.item])
			self.assertTrue(first["ran"], first)
			self.assertEqual((first["alerts"], first["errors"]), (1, []), first)
			made = self.requests()
			self.assertEqual([(r.kind, r.status) for r in made], [(KIND_REORDER, "pending")])
			run_stock_check(items=[self.item])
		self.assertEqual(self.requests(), made, "the same request is still the only one")

	def test_nothing_is_asked_for_when_the_stock_is_enough(self):
		make_stock_entry(item_code=self.item, qty=50, to_warehouse=WAREHOUSE, rate=10)
		with free_lease():
			report = run_stock_check(items=[self.item])
		self.assertEqual((report["ran"], report["alerts"], self.requests()), (True, 0, []))

	def test_a_rule_that_is_zero_is_not_used(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		settings = frappe.get_doc("AI Munimji Settings")
		settings.min_qty = 0
		settings.save()
		with free_lease():
			self.assertEqual(run_stock_check(items=[self.item])["alerts"], 0)

	def test_the_job_does_nothing_on_a_site_where_nobody_has_switched_the_monitor_on(self):
		# a new install is off by default (docs/NAMES.md): an item far below the quantity gets no request, whatever else is set
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		for rows_left in ("no page at all", "a page with the threshold but no switch"):
			frappe.db.delete("Singles", {"doctype": "AI Munimji Settings"})
			frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")
			if rows_left != "no page at all":
				frappe.db.set_single_value("AI Munimji Settings", "min_qty", 10)
			self.assertFalse(frappe.get_cached_doc("AI Munimji Settings").enabled, rows_left)
			self.assertEqual(check_stock(), 0, rows_left)
			self.assertEqual(self.requests(), [], rows_left)

	def test_the_job_does_nothing_when_it_is_switched_off(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		settings = frappe.get_doc("AI Munimji Settings")
		settings.enabled = 0
		settings.save()
		self.assertEqual(run_stock_check(items=[self.item])["ran"], False)
		self.assertEqual(self.requests(), [])

	def test_the_job_reads_and_proposes_and_never_makes_a_document(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		before = {d: frappe.db.count(d) for d in ("Purchase Order", "Material Request")}
		with free_lease():
			run_stock_check(items=[self.item])
		self.assertEqual({d: frappe.db.count(d) for d in before}, before)

	def test_a_second_tick_while_the_first_holds_the_lease_does_nothing(self):
		# the lease itself (two real connections, the expiry) is tested in tests/world/test_end_to_end.py; here only what the job does when it is refused
		with mock.patch.object(locks, "lease", return_value=False):
			report = run_stock_check(items=[self.item])
		self.assertEqual((report["ran"], report["requests"]), (False, 0))
		self.assertIn("another run", report["why"])
		self.assertEqual(self.requests(), [])

	def test_a_run_that_fails_is_recorded_and_gives_the_lease_back(self):
		def boom(self, **kwargs):
			raise RuntimeError("the ERP is down")

		released = mock.Mock(return_value=None)
		# no commit and no rollback of the test's own transaction: the job's commit and rollback are what they would do to the site, and are not what is looked at here
		with (
			mock.patch.multiple(locks, lease=mock.Mock(return_value=True), release=released),
			mock.patch.object(frappe.db, "commit"),
			mock.patch.object(frappe.db, "rollback"),
			mock.patch.object(InventoryAgent, "run", boom),
			self.assertRaises(RuntimeError),
		):
			run_stock_check(items=[self.item])
		row = frappe_core_stores(system=True).jobs.get(jobs.STOCK_CHECK)
		self.assertEqual((row["last_ok"], row["failures"]), (0, 1))
		self.assertIn("the ERP is down", row["last_error"])
		released.assert_called_once()

	def fail_for(self, code: str):
		"""The engine's analysis of one item raises; every other item is analysed as before."""
		real = agent_module.analyze_item

		def analyse(item, *args, **kwargs):
			if item.code == code:
				raise RuntimeError("planted failure")
			return real(item, *args, **kwargs)

		return mock.patch.object(agent_module, "analyze_item", analyse)

	def test_an_item_that_cannot_be_analysed_is_counted_kept_with_the_run_and_said_on_the_settings_page(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		with free_lease(), self.fail_for(self.item):
			report = run_stock_check(items=[self.item])
		self.assertTrue(report["ran"], "the run goes on, and ends well")
		self.assertEqual(report["unanalysed"], 1)
		self.assertTrue(
			any(e.startswith(f"{self.item}: analysis failed") for e in report["errors"]), report["errors"]
		)
		self.assertEqual(
			(report["alerts"], self.requests()), (0, []), "nothing is made from an item that was not analysed"
		)
		row = frappe_core_stores(system=True).jobs.get(jobs.STOCK_CHECK)
		self.assertEqual(
			(row["last_ok"], row["failures"], row["last_error"]), (1, 0, "1 item could not be analysed")
		)

		manager = make_user("skipped.manager@example.com", ("Munimji Manager",))
		frappe.set_user(manager)
		page = frappe.get_doc("AI Munimji Settings")
		page.onload()
		self.assertEqual(page.get_onload("unanalysed_items"), 1)
		frappe.set_user(make_user("skipped.viewer@example.com", ("Munimji Viewer",)))
		self.assertEqual(
			last_run.unanalysed_in_last_check(),
			0,
			"a person who may not read job records is told nothing, and nothing fails",
		)
		frappe.set_user("Administrator")

	def test_the_note_keeps_the_other_notes_and_goes_when_every_item_is_analysed(self):
		make_stock_entry(item_code=self.item, qty=3, to_warehouse=WAREHOUSE, rate=10)
		with free_lease(), self.fail_for(self.item):
			run_stock_check(items=[self.item])
		self.assertEqual(last_run.unanalysed_in_last_check(), 1)
		with free_lease():
			report = run_stock_check(items=[self.item])
		self.assertEqual(
			(report["unanalysed"], report["alerts"]),
			(0, 1),
			"the next run analyses it and raises its request",
		)
		self.assertEqual(last_run.unanalysed_in_last_check(), 0)
		page = frappe.get_doc("AI Munimji Settings")
		page.onload()
		self.assertNotIn("unanalysed_items", page.get("__onload") or {})

	def test_a_run_that_fails_has_no_note_of_skipped_items(self):
		core = frappe_core_stores(system=True)
		core.jobs.started(jobs.STOCK_CHECK, "2026-11-09T06:00:00+00:00")
		core.jobs.finished(
			jobs.STOCK_CHECK, "2026-11-09T06:00:01+00:00", False, "1 item could not be analysed"
		)
		self.assertEqual(last_run.unanalysed_in_last_check(), 0, "only a run that went well carries the note")

	def test_the_system_mode_of_the_stores_is_administrators_alone(self):
		self.assertTrue(jobs.system_stores().approvals)
		frappe.set_user(make_user("jobs.manager@example.com", ("Munimji Manager", "System Manager")))
		with self.assertRaises(frappe.PermissionError):
			jobs.system_stores()
		frappe.set_user("Administrator")

	def test_the_schedule_is_registered_as_a_scheduled_job_type(self):
		scheduled = frappe.get_all(
			"Scheduled Job Type",
			filters={"method": "ai_munimji.jobs.check_stock"},
			fields=["frequency", "cron_format", "stopped", "scheduler_event"],
		)
		page = frappe.get_doc("AI Munimji Settings")
		self.assertEqual(
			[(j.frequency, j.cron_format, j.stopped, bool(j.scheduler_event)) for j in scheduled],
			[("Cron", page.check_cron, 0 if page.enabled else 1, True)],
			"one job, on the page's schedule, stopped while Watch stock is off, standing on a Scheduler Event",
		)
		self.assertEqual(
			frappe.get_hooks("scheduler_events").get("cron", {}).get("*/5 * * * *", []),
			[],
			"and not declared in hooks.py, where a migrate would reset it",
		)
