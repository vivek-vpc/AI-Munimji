"""From "Approve" on a reorder request to the purchase request, and the sentence a person reads after every answer (Group 2, F1 and F2 of the production-readiness review).

Approving a reorder used to leave the vendor comparison to the next scheduled check (up to a day later) and told the person only that their answer was "recorded". Now the answer queues a
background job once it is committed, the job compares the vendors for that one reorder as Administrator under the stock check's lease, and each answer says in one plain sentence what
happens next and where to look. What is shown here, on a stock that is a fake ERP client's (tests/helpers.py), so that it needs no ERPNext data:

  * the answer queues one job, after the commit, for the work order it made (and none while Watch stock is off, or when the queue cannot be reached: the answer stands and the sentence
    says the next scheduled check will do it);
  * the job runs as Administrator in the system mode even when it was queued by a person, makes the purchase request, and leaves other waiting reorders alone;
  * the scheduled check that follows makes no second purchase request for the same reorder; a job that cannot take the lease does nothing and the scheduled check makes the request;
  * every answer is followed by its sentence: reorder approved, purchase request approved (with the draft order's number as a link), closed, snoozed, handled by hand.
"""

from contextlib import contextmanager
from unittest import mock

import frappe
from ai_munimji_engine.core.workorders import REORDER_NEEDED
from ai_munimji_engine.packs.stock_procurement.erp import PurchaseOrderResult
from frappe.tests import IntegrationTestCase

from ai_munimji import api, hand_off, jobs, wiring
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.tests.helpers import APPROVER_ROLES, FakeStock, empty_store_tables, make_user
from ai_munimji.tests.test_jobs import free_lease

REQUEST, SETTINGS = "Munimji Approval Request", "AI Munimji Settings"
APPROVED_REORDER = "Approved. The vendors are being compared; the purchase request will appear in Munimji Approval Request in about a minute."


class FakeBuyer(FakeStock):
	"""A fake stock that can also be bought from: `made` holds the drafts it was asked to create. `offers=False` is an item with no purchase history."""

	def __init__(self, count=2, low=(0,), offers=True, item_name=None, supplier_name=None):
		super().__init__(count, low)
		self.offers, self.made = offers, []
		self.item_name, self.supplier_name = item_name, supplier_name

	def list_items(self):
		items = super().list_items()
		if self.item_name:
			from dataclasses import replace

			items = [replace(i, name=f"{self.item_name} {i.code}") for i in items]
		return items

	def get_vendor_offers(self, item_code, since, quotes=None):
		if not self.offers:
			return []
		offers = super().get_vendor_offers(item_code, since, quotes)
		if self.supplier_name:
			from dataclasses import replace

			offers = [replace(o, name=self.supplier_name) for o in offers]
		return offers

	def item_min_order_qty(self, item_code):
		return None

	def create_purchase_order(self, draft, acting=None):
		self.made.append(draft)
		return PurchaseOrderResult(ok=True, name=f"PUR-ORD-FAKE-{len(self.made):04d}")


class FlowCase(IntegrationTestCase):
	"""A site with the monitor switched on, three people, and a fake stock with one item that is low."""

	erp: FakeBuyer

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.approver = make_user("flow.approver@example.com", APPROVER_ROLES)
		cls.viewer = make_user("flow.viewer@example.com", ("Munimji Viewer",))
		cls.manager = make_user("flow.manager@example.com", ("Munimji Manager",))

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"flow_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		page = frappe.get_doc(SETTINGS)
		page.enabled, page.min_qty, page.min_days_cover, page.stock_alerts = 1, 10, 0, 0
		page.save()
		self.erp = self.make_erp()
		self.enqueued = mock.patch("frappe.enqueue").start()
		self.addCleanup(mock.patch.stopall)
		mock.patch.object(jobs, "system_erp", lambda company=None: self.erp).start()
		mock.patch.object(wiring, "FrappeERPClient", lambda *a, **k: self.erp).start()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def make_erp(self) -> FakeBuyer:
		return FakeBuyer()

	def queued(self) -> list:
		"""The vendor comparisons that were queued (Frappe queues other jobs too, for example the notification of a new request)."""
		return [c for c in self.enqueued.call_args_list if c.args and c.args[0] == hand_off.JOB]

	# ------------------------------------------------------------------ the people and the requests
	def pending(self, kind: str | None = None) -> list[dict]:
		rows = frappe_core_stores(system=True).approvals.list("pending", 100)
		return [r for r in rows if kind is None or r["kind"] == kind]

	def scheduled_check(self) -> dict:
		with free_lease():
			return jobs.run_stock_check()

	def raise_a_reorder(self) -> str:
		report = self.scheduled_check()
		self.assertEqual(report["alerts"], 1, report)
		(request,) = self.pending("inventory.reorder")
		return request["id"]

	def answer(self, request_id: str, action: str, user: str | None = None, **params) -> dict:
		import json

		frappe.set_user(user or self.approver)
		try:
			return api.answer(request_id, action, json.dumps(params) if params else None)
		finally:
			frappe.set_user("Administrator")

	def waiting_work_orders(self) -> list[dict]:
		return frappe_core_stores(system=True).workorders.list("pending", REORDER_NEEDED, 100)

	def the_job(self, work_order_id: str, as_user: str | None = None) -> dict:
		"""The queued job, run the way a worker runs it: as whoever queued it (the approver), by the function that was queued."""
		frappe.set_user(as_user or self.approver)
		try:
			with free_lease():
				return jobs.run_vendor_comparison(work_order_id)
		finally:
			frappe.set_user("Administrator")


class TestApprovingAReorderQueuesTheComparison(FlowCase):
	def test_the_answer_queues_one_job_after_the_commit_for_the_work_order_it_made_and_says_so(self):
		request = self.raise_a_reorder()
		self.assertEqual(self.queued(), [])
		said = self.answer(request, "approve")
		(work_order,) = self.waiting_work_orders()
		self.assertTrue(said["ok"], said)
		self.assertEqual(said["message"], APPROVED_REORDER)
		self.assertEqual(
			self.queued(),
			[
				mock.call(
					"ai_munimji.jobs.run_vendor_comparison",
					queue="long",
					timeout=hand_off.TIMEOUT,
					enqueue_after_commit=True,
					work_order_id=work_order["id"],
				)
			],
		)
		self.assertEqual(self.pending("procurement.po"), [], "nothing is made in the person's own request")

	def test_the_sentence_names_the_place_to_look_as_a_link(self):
		said = self.answer(self.raise_a_reorder(), "approve")
		self.assertIn(
			'<a href="/app/munimji-approval-request">Munimji Approval Request</a>', said["message_html"]
		)
		self.assertNotIn("<a", said["message"], "the plain text has no markup")

	def test_nothing_is_queued_while_watch_stock_is_off_and_the_sentence_says_so(self):
		request = self.raise_a_reorder()
		page = frappe.get_doc(SETTINGS)
		page.enabled = 0
		page.save()
		said = self.answer(request, "approve")
		self.assertTrue(said["ok"], said)
		self.assertEqual(self.queued(), [])
		self.assertTrue(said["message"].startswith("Approved. Watch stock is switched off"), said["message"])
		self.assertEqual(
			len(self.waiting_work_orders()), 1, "the work order waits for the check that follows a switch-on"
		)

	def test_a_queue_that_cannot_be_reached_does_not_undo_the_answer(self):
		request = self.raise_a_reorder()
		self.enqueued.side_effect = (
			lambda method, *a, **k: (_ for _ in ()).throw(ConnectionError("redis is down"))
			if method == hand_off.JOB
			else None
		)
		said = self.answer(request, "approve")
		self.assertTrue(said["ok"], said)
		self.assertEqual(said["status"], "decided")
		self.assertTrue(
			said["message"].startswith("Approved. The vendors will be compared by the next scheduled check"),
			said["message"],
		)
		self.assertEqual(len(self.waiting_work_orders()), 1, "the scheduled check will find it")

	def test_a_stock_check_running_just_now_is_said(self):
		request = self.raise_a_reorder()
		with mock.patch.object(locks, "held", return_value=True):
			said = self.answer(request, "approve")
		self.assertTrue(
			said["message"].startswith("Approved. A stock check is running just now"), said["message"]
		)
		self.assertIn("next scheduled check", said["message"])
		self.assertEqual(len(self.queued()), 1, "the job still tries: it may find the lease free")

	def test_a_sentence_that_cannot_be_made_does_not_turn_the_answer_into_an_error(self):
		from ai_munimji import next_step

		request = self.raise_a_reorder()
		with mock.patch.object(next_step, "after_answer", side_effect=RuntimeError("no sentence today")):
			said = self.answer(request, "approve")
		self.assertTrue(said["ok"], said)
		self.assertEqual(said["status"], "decided")
		self.assertTrue(said["message"].startswith("Recorded: "), "the engine's own words stand")
		self.assertNotIn("message_html", said)
		self.assertEqual(len(self.queued()), 1, "and the comparison is still queued")

	def test_a_reorder_that_is_dismissed_or_snoozed_queues_nothing(self):
		request = self.raise_a_reorder()
		said = self.answer(request, "dismiss")
		self.assertEqual(said["message"], "Closed. Nothing was ordered.")
		self.assertEqual(self.queued(), [])
		self.assertEqual(self.waiting_work_orders(), [])


class TestTheJob(FlowCase):
	def approved_reorder(self) -> str:
		self.answer(self.raise_a_reorder(), "approve")
		(work_order,) = self.waiting_work_orders()
		return work_order["id"]

	def test_it_makes_the_purchase_request_as_administrator_in_the_system_mode(self):
		work_order = self.approved_reorder()
		seen = []
		real = jobs.system_services

		def spy(*args, **kwargs):
			seen.append(frappe.session.user)
			return real(*args, **kwargs)

		with mock.patch.object(jobs, "system_services", spy):
			report = self.the_job(work_order, as_user=self.approver)
		self.assertEqual(
			seen, ["Administrator"], "queued by the approver, it does not run in the approver's session"
		)
		self.assertEqual((report["ran"], report["proposals"], report["errors"]), (True, 1, []), report)
		(purchase,) = self.pending("procurement.po")
		self.assertEqual(purchase["ref_type"], "procurement_proposal")
		self.assertEqual(self.waiting_work_orders(), [], "the work order is claimed")

	def test_the_scheduled_check_after_it_makes_no_second_purchase_request(self):
		work_order = self.approved_reorder()
		self.the_job(work_order)
		report = self.scheduled_check()
		self.assertEqual((report["considered"], report["proposals"]), (0, 0), report)
		self.assertEqual(len(self.pending("procurement.po")), 1, "one purchase request for the one reorder")

	def test_the_job_that_runs_twice_makes_one_request(self):
		work_order = self.approved_reorder()
		self.the_job(work_order)
		again = self.the_job(work_order)
		self.assertEqual(again["requests"], 0)
		self.assertEqual(len(self.pending("procurement.po")), 1)

	def test_a_job_that_cannot_take_the_lease_does_nothing_and_the_scheduled_check_makes_the_request(self):
		work_order = self.approved_reorder()
		frappe.set_user(self.approver)
		try:
			with (
				mock.patch.object(locks, "lease", return_value=False),
				mock.patch.object(jobs, "system_services") as built,
			):
				report = jobs.run_vendor_comparison(work_order)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual((report["ran"], report["why"]), (False, "another run is under way"))
		built.assert_not_called()
		self.assertEqual(len(self.waiting_work_orders()), 1, "still waiting")
		self.assertEqual(self.pending("procurement.po"), [])
		self.scheduled_check()
		self.assertEqual(len(self.pending("procurement.po")), 1, "the next scheduled check made it")
		self.assertEqual(self.waiting_work_orders(), [])

	def test_it_takes_the_work_order_it_was_queued_for_and_no_other(self):
		self.erp = FakeBuyer(count=3, low=(0, 1))
		self.assertEqual(self.scheduled_check()["alerts"], 2)
		for request in self.pending("inventory.reorder"):
			self.answer(request["id"], "approve")
		first, second = (w["id"] for w in self.waiting_work_orders())
		self.the_job(first)
		self.assertEqual(
			[w["id"] for w in self.waiting_work_orders()],
			[second],
			"the other reorder is left for the scheduled check",
		)
		self.assertEqual(len(self.pending("procurement.po")), 1)
		self.scheduled_check()
		self.assertEqual(len(self.pending("procurement.po")), 2, "and the scheduled check makes its request")

	def test_it_does_nothing_while_watch_stock_is_off(self):
		work_order = self.approved_reorder()
		page = frappe.get_doc(SETTINGS)
		page.enabled = 0
		page.save()
		report = self.the_job(work_order)
		self.assertEqual((report["ran"], report["why"]), (False, "Watch stock is off"))
		self.assertEqual(len(self.waiting_work_orders()), 1)

	def test_a_failure_leaves_the_work_order_waiting_for_the_scheduled_check(self):
		work_order = self.approved_reorder()
		with mock.patch.object(self.erp, "get_vendor_offers", side_effect=RuntimeError("ERPNext is down")):
			report = self.the_job(work_order)
		self.assertEqual(report["errors"], ["FS-000: ERPNext is down"], report)
		self.assertEqual(len(self.waiting_work_orders()), 1, "the work order was not claimed")
		self.scheduled_check()
		self.assertEqual(len(self.pending("procurement.po")), 1)


class TestWhatIsSaidAfterEachAnswer(FlowCase):
	def purchase_request(self) -> str:
		self.answer(self.raise_a_reorder(), "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(purchase,) = self.pending("procurement.po")
		return purchase["id"]

	def test_a_purchase_request_approved_names_the_draft_order_and_links_it(self):
		said = self.answer(self.purchase_request(), "approve")
		self.assertTrue(said["ok"], said)
		self.assertEqual(
			said["message"], "Draft Purchase Order PUR-ORD-FAKE-0001 made. Review and submit it in ERPNext."
		)
		self.assertEqual(
			said["message_html"],
			'Draft Purchase Order <a href="/app/purchase-order/PUR-ORD-FAKE-0001">PUR-ORD-FAKE-0001</a> made. Review and submit it in ERPNext.',
		)
		self.assertEqual(said["document"]["doctype"], "Purchase Order")
		self.assertEqual(said["document"]["path"], "/app/purchase-order/PUR-ORD-FAKE-0001")

	def test_the_number_of_the_order_is_not_trusted_as_markup(self):
		with mock.patch.object(
			self.erp, "create_purchase_order", return_value=PurchaseOrderResult(ok=True, name="PO-<b>1</b>")
		):
			said = self.answer(self.purchase_request(), "approve")
		self.assertNotIn("<b>", said["message_html"])
		self.assertIn("PO-&lt;b&gt;1&lt;/b&gt;", said["message_html"])

	def test_a_purchase_request_dismissed_says_nothing_was_ordered(self):
		said = self.answer(self.purchase_request(), "dismiss")
		self.assertEqual(said["message"], "Closed. Nothing was ordered.")
		self.assertEqual(self.erp.made, [])

	def test_a_purchase_request_snoozed_says_when_it_comes_back(self):
		said = self.answer(self.purchase_request(), "snooze")
		self.assertTrue(said["message"].startswith("Snoozed. You will be asked again on "), said["message"])
		self.assertTrue(said["message"].endswith("Nothing was ordered."), said["message"])

	def test_a_reorder_snoozed_says_when_it_comes_back(self):
		said = self.answer(self.raise_a_reorder(), "snooze")
		self.assertTrue(said["message"].startswith("Snoozed. You will be asked again on "), said["message"])


class TestARequestWithNoVendorHistory(FlowCase):
	def make_erp(self) -> FakeBuyer:
		return FakeBuyer(offers=False)

	def manual_request(self) -> str:
		self.answer(self.raise_a_reorder(), "approve")
		(work_order,) = self.waiting_work_orders()
		report = self.the_job(work_order["id"])
		self.assertEqual((report["proposals"], report["manual"]), (0, 1), report)
		(manual,) = self.pending("procurement.manual")
		return manual["id"]

	def test_the_job_makes_a_request_that_asks_for_a_hand_made_order(self):
		request = self.manual_request()
		self.assertEqual(self.pending("procurement.po"), [])
		self.assertTrue(request)

	def test_pressing_got_it_says_nothing_was_ordered_and_the_order_is_by_hand(self):
		said = self.answer(self.manual_request(), "ack")
		self.assertTrue(said["ok"], said)
		self.assertEqual(
			said["message"],
			"Marked as handled. Nothing was ordered from here: order it in ERPNext by hand if it is not ordered yet.",
		)


class TestTheSentencesOfKindsAndAnswersNotMadeAbove(IntegrationTestCase):
	"""`next_step.after_answer` on stand-ins for the engine's records, for the answers that the flow above does not reach."""

	def record(self, kind, action, status="decided"):
		from types import SimpleNamespace

		decision = SimpleNamespace(action=action) if action else None
		return SimpleNamespace(id="r1", kind=kind, status=status, decision=decision)

	def services(self, proposal=None, alert=None, notice=None):
		from types import SimpleNamespace

		return SimpleNamespace(
			hand_off=None,
			proposals=SimpleNamespace(by_approval=lambda _id: proposal),
			alerts=SimpleNamespace(by_approval=lambda _id: alert),
			inventory=SimpleNamespace(notices=SimpleNamespace(by_approval=lambda _id: notice)),
		)

	def proposal(self, po_name, document="order"):
		from types import SimpleNamespace

		return SimpleNamespace(
			status="ordered", po_name=po_name, ranking={"document": document}, snoozed_until=None
		)

	def test_orders_switched_off_says_that_no_order_was_made(self):
		from ai_munimji import next_step

		said = next_step.after_answer(
			self.record("procurement.po", "approve"), self.services(self.proposal(None))
		)
		self.assertEqual(
			said.text,
			"Approved. No order was made in ERPNext: creating orders is switched off in the procurement settings.",
		)
		self.assertIsNone(said.document)

	def test_a_requisition_names_the_material_request_and_links_it(self):
		from ai_munimji import next_step

		said = next_step.after_answer(
			self.record("procurement.pr", "approve"),
			self.services(self.proposal("MAT-MR-0001", "requisition")),
		)
		self.assertEqual(
			said.text,
			"Draft purchase requisition MAT-MR-0001 made. Your buyer turns it into an order in ERPNext.",
		)
		self.assertIn('href="/app/material-request/MAT-MR-0001"', said.html)
		self.assertEqual(said.document, ("Material Request", "MAT-MR-0001"))

	def test_a_notice_acknowledged_and_a_notice_snoozed(self):
		from types import SimpleNamespace

		from ai_munimji import next_step

		self.assertEqual(
			next_step.after_answer(self.record("inventory.alert", "ack"), self.services()).text,
			"Got it. This was for your information: nothing was ordered.",
		)
		said = next_step.after_answer(
			self.record("inventory.alert", "snooze"),
			self.services(notice=SimpleNamespace(snoozed_until=frappe.utils.now_datetime())),
		)
		self.assertTrue(said.text.startswith("Snoozed. You will be asked again on "), said.text)

	def test_the_engines_own_words_stand_for_what_this_module_does_not_know(self):
		from ai_munimji import next_step

		for record in (
			self.record("procurement.order", "keep"),
			self.record("inventory.monitor_down", "ack"),
			self.record("procurement.po", "approve", status="pending"),
			self.record("something.new", "approve"),
		):
			self.assertIsNone(next_step.after_answer(record, self.services(self.proposal("X"))), record.kind)
