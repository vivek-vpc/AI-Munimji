"""From the stock on the shelf to a draft Purchase Order, on real data with real users, by function call (the scheduler and the Desk screens are Phase 5's).

  the job (the system-mode client and stores) reads the stock of the contract world -> an alert and a request to start a reorder -> a person approves it -> the job turns it into a
  proposal with its comparison, its reasons and the tax figures it read -> a person approves the order -> a Draft Purchase Order carrying the request's reference and the person's name
  -> a second press is refused -> the job seals what was answered, the seal checks out, and a tampered answer is found.

Every call to the ERP is recorded. The seven methods the Frappe client leaves out (docs/KNOWN_LIMITATIONS.md) are not on this path: the test fails if one of them is called, and says which
methods were.
"""

import json
import threading
from contextlib import contextmanager
from unittest import mock

import frappe
from ai_munimji_engine.core.workorders import REORDER_NEEDED
from ai_munimji_engine.packs.stock_procurement.inventory.agent import InventoryAgent, RunReport
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND as KIND_REORDER
from ai_munimji_engine.packs.stock_procurement.procurement.messages import KIND_PO
from ai_munimji_engine.packs.stock_procurement.procurement.proposals import ProposalRepo

from ai_munimji import api, jobs, schedule, wiring
from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.stores.core import FrappeJobRunStore
from ai_munimji.tests.helpers import empty_store_tables
from ai_munimji.tests.world import as_administrator, as_user
from ai_munimji.tests.world.parallel import ParallelCase, on_own_connections

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"
LEFT_OUT = (
	"get_receipt_lines",
	"get_stock_counts",
	"get_stock_values",
	"last_purchase_dates",
	"get_item_alternatives",
	"send_email",
	"get_supplier_contact",
)
SETTING_FIELDS = ("enabled", "min_qty", "min_days_cover", "stock_alerts")


class Recorder:
	"""Stands between the engine and the ERP client and notes every method called. A call to one of the methods the client leaves out is noted as such (and still answers as the client does)."""

	def __init__(self, inner, who: str, trace: list):
		self._inner, self._who, self._trace = inner, who, trace

	def __getattr__(self, name):
		attr = getattr(self._inner, name)
		if not callable(attr):
			return attr

		def call(*args, **kwargs):
			self._trace.append((self._who, name))
			return attr(*args, **kwargs)

		return call


@contextmanager
def the_job_is_recorded(trace: list):
	with mock.patch.object(
		jobs,
		"system_erp",
		lambda company=None: Recorder(FrappeERPClient(system=True, company=company), "job", trace),
	):
		yield


class EndToEnd(ParallelCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		page = frappe.get_doc(SETTINGS)
		cls.before = {f: page.get(f) for f in SETTING_FIELDS}
		page.enabled, page.min_qty, page.min_days_cover, page.stock_alerts = (
			1,
			300,
			0,
			0,
		)  # the steady item holds 240: at or below the quantity, so it is low; no information-only notice first
		page.save()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		page = frappe.get_doc(SETTINGS)
		for field, value in cls.before.items():
			page.set(field, value)
		page.save()
		empty_store_tables()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		empty_store_tables()
		frappe.db.delete("Notification Log", {"document_type": REQUEST})
		frappe.db.commit()
		self.item = self.names["steady"]
		self.trace: list = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"Purchase Order",
			filters={
				"owner": ["in", [self.person("approver")]],
				"docstatus": 0,
				"creation": [">", frappe.utils.add_days(frappe.utils.now(), -1)],
			},
			pluck="name",
		):
			self.remember("Purchase Order", name)
		empty_store_tables()
		frappe.db.delete("Notification Log", {"document_type": REQUEST})
		frappe.db.commit()

	def pending(self, kind: str) -> list[dict]:
		with as_administrator():
			return [
				r for r in frappe_core_stores(system=True).approvals.list("pending", 100) if r["kind"] == kind
			]

	def person_services(self, user: str):
		return wiring.build(Recorder(FrappeERPClient(), user, self.trace), frappe_core_stores(), None)

	def waiting_reorder(self):
		"""A reorder a person has approved, waiting for the procurement pass: the work order the inventory agent would have made."""
		with as_administrator():
			services = jobs.system_services()
			services.workorders.emit(
				REORDER_NEEDED,
				{
					"item_code": self.item,
					"item_name": self.item,
					"item_group": "All Item Groups",
					"uom": "Nos",
					"suggested_qty": 100,
					"cover_days": 20.0,
					"lead_time_days": 5.0,
					"daily_rate": 4.0,
					"on_hand": 10.0,
					"severity": "HIGH",
					"reasons": ["Low."],
				},
			)
		frappe.db.commit()

	@staticmethod
	def slowed(original):
		"""The look for an open proposal, made to wait until both ticks have read the waiting reorders (so neither can have claimed it before the other looked), and then a moment more."""
		meeting = threading.Barrier(2)

		def slow(self, *args, **kwargs):
			found = original(self, *args, **kwargs)
			try:
				meeting.wait(4)  # with the lease only one tick gets here, and goes on after the wait
			except threading.BrokenBarrierError:
				pass
			return found

		return slow

	def two_ticks(self, tick=None):
		"""Two ticks on two connections, both made to reach the pass over the waiting reorders together. `tick` is what each runs (the stock check of this item unless said)."""
		tick = tick or (lambda: jobs.run_stock_check(items=[self.item]))

		def no_stock_pass(
			agent, **kwargs
		):  # what is tested is the pass over the waiting reorders: both ticks must reach it together
			return RunReport(run_id="x", dry_run=False, started_at="2026-10-16T08:00:00+00:00")

		with (
			mock.patch.object(ProposalRepo, "open_for_item", self.slowed(ProposalRepo.open_for_item)),
			mock.patch.object(InventoryAgent, "run", no_stock_pass),
		):
			return on_own_connections("Administrator", [tick] * 2)

	def proposals(self):
		with as_administrator():
			frappe.db.commit()
			return wiring.build(
				FrappeERPClient(system=True), frappe_core_stores(system=True)
			).stock.proposals.list(None, self.item, 10)


class TestFromTheStockToADraftOrder(EndToEnd):
	def test_the_whole_way(self):
		# 1. the job reads the stock
		with as_administrator(), the_job_is_recorded(self.trace):
			first = jobs.run_stock_check(items=[self.item])
		self.assertTrue(first["ran"], first)
		self.assertGreaterEqual(first["alerts"], 1, first)
		reorder = [r for r in self.pending(KIND_REORDER)]
		self.assertEqual(len(reorder), 1, "one request to start a reorder, for the one item looked at")
		self.assertEqual(
			frappe.db.get_value(REQUEST, reorder[0]["id"], "item_code"),
			self.item,
			"the list view can filter by the item",
		)

		# 2. a person who may only look cannot answer; a person who may approve starts the reorder
		with as_user("viewer"):
			refused = self.person_services("viewer").approvals.decide(
				reorder[0]["id"], "approve", wiring.actor_for(), "desk"
			)
		self.assertFalse(refused.ok, refused)
		with as_user("approver"):
			started = self.person_services("approver").approvals.decide(
				reorder[0]["id"], "approve", wiring.actor_for(), "desk"
			)
		self.assertTrue(started.ok, started)
		frappe.db.commit()

		# 3. the job turns it into a proposal with its reasons and the tax figures it read (the job may read Tax Rules; a Purchase User may not)
		with as_administrator(), the_job_is_recorded(self.trace):
			second = jobs.run_stock_check(items=[self.item])
		self.assertTrue(second["ran"], second)
		self.assertEqual((second["proposals"], second["errors"]), (1, []), second)
		with as_administrator():
			stock = wiring.build(FrappeERPClient(system=True), frappe_core_stores(system=True)).stock
			[proposal] = stock.proposals.list(None, self.item, 10)
		ranking = frappe.parse_json(proposal["ranking_json"])
		self.assertTrue(ranking["vendors"], "the comparison is kept")
		self.assertIn("tax_setups", ranking, "and so are the tax figures the job read")
		self.assertTrue(any(v.get("eligible") for v in ranking["vendors"]))
		po_requests = self.pending(KIND_PO)
		self.assertEqual(len(po_requests), 1)

		# 4. the approver approves the order: a Draft Purchase Order, in their name, carrying the proposal's reference
		with as_user("approver"):
			ordered = self.person_services("approver").approvals.decide(
				po_requests[0]["id"], "approve", wiring.actor_for(), "desk"
			)
		self.assertTrue(ordered.ok, ordered)
		frappe.db.commit()
		with as_administrator():
			made = frappe_core_stores(system=True)
			po_name = wiring.build(FrappeERPClient(system=True), made).stock.proposals.get(proposal["id"])[
				"po_name"
			]
		self.assertTrue(po_name, "the proposal says which order it led to")
		self.remember("Purchase Order", po_name)
		po = frappe.get_doc("Purchase Order", po_name)
		self.assertEqual(
			(po.docstatus, po.supplier, po.owner),
			(0, proposal["supplier"], self.person("approver")),
			"a draft, for the recommended supplier, made by the approver",
		)
		self.assertEqual(po.items[0].item_code, self.item)
		self.assertEqual(
			po.get("custom_agent_ref"),
			proposal["id"],
			"it carries the proposal's reference, which is how a second press is recognised",
		)
		self.assertIn(self.person("approver"), po.get("custom_agent_approved_by"))

		# 5. a second press is refused and makes nothing
		with as_user("approver"):
			again = self.person_services("approver").approvals.decide(
				po_requests[0]["id"], "approve", wiring.actor_for(), "desk"
			)
		self.assertFalse(again.ok, again)
		self.assertEqual(
			frappe.db.count("Purchase Order", {"custom_agent_ref": proposal["id"], "docstatus": ["<", 2]}), 1
		)
		with as_user("approver"):
			same = FrappeERPClient().create_purchase_order(
				__import__(
					"ai_munimji_engine.packs.stock_procurement.erp", fromlist=["PurchaseOrderDraft"]
				).PurchaseOrderDraft(
					supplier=po.supplier,
					item_code=self.item,
					qty=1,
					rate=1.0,
					uom="Nos",
					required_by=self.required_by(),
					reference=proposal["id"],
					approved_by="approver via desk",
				)
			)
		self.assertEqual(
			same.name, po_name, "even asked of the client directly, the same reference gives the same order"
		)

		# 6. the seal: what has been answered is sealed by the job, the chain checks out, and a changed answer is found
		with as_administrator(), the_job_is_recorded(self.trace):
			third = jobs.run_stock_check(items=[self.item])
		self.assertEqual(
			second["sealed"] + third["sealed"],
			2,
			"the reorder request was sealed by the tick after it was answered, the order request by the next",
		)
		with as_administrator():
			services = wiring.build(FrappeERPClient(system=True), frappe_core_stores(system=True))
			verdict = services.audit.verify()
			self.assertTrue(verdict["ok"], verdict)
			self.assertGreaterEqual(verdict["entries"], 2)
			frappe.db.set_value(
				REQUEST, po_requests[0]["id"], "decision_json", '{"action":"reject","actor_id":"someone"}'
			)
			self.assertFalse(services.audit.verify()["ok"], "a changed answer is found")
			frappe.db.rollback()

		# 7. the seven methods the client leaves out are not on this path
		used = sorted({name for _who, name in self.trace})
		self.assertEqual(
			sorted(set(used) & set(LEFT_OUT)),
			[],
			f"methods the Frappe client does not provide were called: {used}",
		)
		print("\nERP methods called on the whole way:", ", ".join(used))
		self.assertTrue({"get_stock", "get_vendor_offers", "create_purchase_order"} <= set(used), used)

	def test_a_run_with_watch_stock_off_does_nothing(self):
		page = frappe.get_doc(SETTINGS)
		page.enabled = 0
		page.save()
		frappe.db.commit()
		try:
			with as_administrator():
				report = jobs.run_stock_check(items=[self.item])
			self.assertEqual((report["ran"], report["requests"]), (False, 0))
			self.assertEqual(frappe_core_stores(system=True).approvals.list(None, 10), [])
		finally:
			page = frappe.get_doc(SETTINGS)
			page.enabled = 1
			page.save()
			frappe.db.commit()


class TestTwoTicksAtOnce(EndToEnd):
	def test_two_ticks_at_once_make_one_proposal(self):
		self.waiting_reorder()
		results = self.two_ticks()
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual(sorted(r["ran"] for r in results), [False, True], results)
		self.assertIn("another run", next(r["why"] for r in results if not r["ran"]))
		self.assertEqual(len(self.proposals()), 1, "one proposal, not two")
		self.assertEqual(len(self.pending(KIND_PO)), 1)

	def test_the_negative_control_without_the_lease_two_ticks_make_two_proposals(self):
		self.waiting_reorder()
		# the lease is taken away; so is the record of the run, because a second insert of "the stock check ran" waits for the first tick to commit and would serialise them by accident
		with (
			mock.patch.object(locks, "lease", return_value=True),
			mock.patch.object(locks, "release", return_value=None),
			mock.patch.object(FrappeJobRunStore, "started", return_value=None),
			mock.patch.object(FrappeJobRunStore, "finished", return_value=None),
		):
			results = self.two_ticks()
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual(
			len(self.proposals()),
			2,
			f"without the lease both ticks claim the waiting reorder: the test can fail; the ticks said {results}",
		)

	def test_a_lease_that_was_never_released_runs_out(self):
		with as_administrator():
			self.assertTrue(locks.lease("probe", "a", 5))
			self.assertFalse(locks.lease("probe", "b", 5), "held")
			self.assertTrue(locks.lease("probe", "a", 5), "the holder may renew")
			locks.release("probe", "a")
			self.assertTrue(locks.lease("probe", "b", 5), "released")
			locks.release("probe", "b")
			self.assertTrue(locks.lease("probe", "a", -1), "a lease of no time at all")
			self.assertTrue(locks.lease("probe", "b", 5), "has run out by the time the next one asks")
			locks.release("probe", "b")


class TestChangingARequest(EndToEnd):
	"""The form's Change quantity and Change vendor buttons carry their answers through api.answer, which also says which request to look at next and the vendors to choose from."""

	def an_order_request(self) -> str:
		self.waiting_reorder()
		with as_administrator():
			jobs.run_stock_check(items=[self.item])
		frappe.db.commit()
		[request] = self.pending(KIND_PO)
		return request["id"]

	def test_changing_the_quantity_replaces_the_request_and_says_which_one_to_open(self):
		old = self.an_order_request()
		with as_user("approver"):
			result = api.answer(old, "change_qty", json.dumps({"qty": 150}))
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["status"], "revised")
		self.assertNotEqual(result["approval"], old, "the revised request is a new one: the form opens it")
		frappe.db.commit()
		[waiting] = self.pending(KIND_PO)
		self.assertEqual(waiting["id"], result["approval"])
		self.assertEqual(frappe.db.get_value(REQUEST, waiting["id"], "qty"), 150)
		self.assertNotEqual(
			frappe.db.get_value(REQUEST, old, "status"), "pending", "and the old one is closed"
		)

	def test_change_vendor_without_a_vendor_lists_the_choices_and_with_one_revises(self):
		old = self.an_order_request()
		with as_user("approver"):
			listed = api.answer(old, "change_vendor")
		self.assertTrue(listed["ok"], listed)
		self.assertEqual(listed["status"], "need_input")
		self.assertTrue(
			listed["choices"] and all({"id", "label"} <= set(c) for c in listed["choices"]), listed
		)
		with as_user("approver"):
			revised = api.answer(old, "change_vendor", json.dumps({"supplier": listed["choices"][0]["id"]}))
		self.assertEqual((revised["ok"], revised["status"]), (True, "revised"), revised)
		self.assertNotEqual(revised["approval"], old)

	def test_a_stale_answer_is_refused_with_the_first_answer_in_the_message(self):
		old = self.an_order_request()
		with as_user("approver"):
			first = api.answer(old, "dismiss")
			second = api.answer(old, "approve")
		self.assertTrue(first["ok"], first)
		self.assertFalse(second["ok"], second)
		self.assertIn("Already answered", second["message"])


class TestTheScheduledJob(EndToEnd):
	"""The job the Settings page switches on is Frappe's own Scheduled Job Type: its record runs the stock check as the scheduler does. Nothing happens while Watch stock is off, one
	proposal is made when it is on, two ticks at once make one, and the people who answer are told once per request, not once per tick."""

	def job(self):
		return frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD})

	def watch_stock(self, on: int):
		page = frappe.get_doc(SETTINGS)
		page.enabled = on
		page.save()
		frappe.db.commit()

	def tick(self):
		"""What the scheduler does with a job that is due: the job record runs its method, as the system."""
		with as_administrator():
			self.job().execute()
		frappe.db.commit()

	def told(self, request_id: str) -> list[str]:
		return [
			row.for_user
			for row in frappe.get_all(
				"Notification Log",
				filters={"document_type": REQUEST, "document_name": request_id},
				fields=["for_user"],
			)
		]

	def test_off_creates_nothing(self):
		self.waiting_reorder()
		self.watch_stock(0)
		self.assertEqual(self.job().stopped, 1)
		self.assertFalse(
			frappe.get_all("Scheduled Job Type", {"method": schedule.METHOD, "stopped": 0}),
			"the scheduler takes the jobs that are not stopped, and this one is",
		)
		self.tick()  # even a tick that someone runs by hand finds Watch stock off
		self.assertEqual(self.proposals(), [])
		self.assertEqual(self.pending(KIND_PO), [])
		self.assertEqual(frappe.db.count("Munimji Job Run"), 0, "not even a record that the check ran")
		self.assertEqual(frappe.db.count(REQUEST), 0)

	def test_on_creates_one_proposal(self):
		self.waiting_reorder()
		self.watch_stock(1)
		self.assertEqual(self.job().stopped, 0)
		self.tick()
		self.assertEqual(len(self.proposals()), 1)
		self.assertEqual(len(self.pending(KIND_PO)), 1)
		log = frappe.get_all(
			"Scheduled Job Log",
			{"scheduled_job_type": self.job().name},
			["status"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(log[0].status, "Complete", "the scheduler's own log says the job ran")
		self.tick()
		self.assertEqual(len(self.proposals()), 1, "the next tick finds it already proposed")

	def test_two_ticks_at_once_give_one_proposal(self):
		self.waiting_reorder()
		self.watch_stock(1)
		name = self.job().name
		results = self.two_ticks(lambda: frappe.get_doc("Scheduled Job Type", name).execute())
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual(len(self.proposals()), 1, "one proposal, not two")
		self.assertEqual(len(self.pending(KIND_PO)), 1)

	def test_one_notification_per_request_not_per_tick(self):
		# Frappe queues the notification logs for a background worker, which this bench does not run; when frappe.in_test is set it writes them at once
		patch = mock.patch.object(frappe, "in_test", True)
		patch.start()
		self.addCleanup(patch.stop)
		self.watch_stock(1)
		with as_administrator():
			jobs.run_stock_check(items=[self.item])
			jobs.run_stock_check(items=[self.item])  # a second tick finds the same request waiting
		frappe.db.commit()
		[reorder] = self.pending(KIND_REORDER)
		told = self.told(reorder["id"])
		self.assertIn(self.person("approver"), told, "the Approver is told")
		self.assertNotIn(self.person("viewer"), told, "the Viewer, who cannot answer, is not")
		self.assertEqual(len(told), len(set(told)), f"nobody twice: {told}")
		self.assertEqual(
			frappe.db.count("Notification Log", {"document_type": REQUEST}),
			len(told),
			"two ticks, one request, one round of notifications",
		)

		with as_user("approver"):
			started = self.person_services("approver").approvals.decide(
				reorder["id"], "approve", wiring.actor_for(), "desk"
			)
		self.assertTrue(started.ok, started)
		frappe.db.commit()
		with as_administrator():
			jobs.run_stock_check(items=[self.item])
		frappe.db.commit()
		[order] = self.pending(KIND_PO)
		self.assertEqual(
			sorted(self.told(order["id"])), sorted(told), "the order request tells the same people, once each"
		)
		self.assertEqual(frappe.db.count("Notification Log", {"document_type": REQUEST}), 2 * len(told))
