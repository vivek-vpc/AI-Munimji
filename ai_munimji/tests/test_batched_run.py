"""The stock check works in batches, each of them committed, and no longer is one transaction for the whole site (finding A1 of the production-readiness review).

What went wrong before: every record the run changed stayed row-locked until the run ended, so a person answering a request the run had touched waited or was told "busy"; a failure near
the end threw away the whole run; and a site too large for the scheduler's 300 seconds never completed a run. What is shown here, on a real database with real commits (the stock is a
fake one: the point is the run, not ERPNext): the batches are committed and the lease renewed after each; a run that dies between batches keeps what the earlier ones did, and running it
again makes each request once; a run that has lost its lease stops; the scheduled entry puts the run on the long queue; the seal is swept in bounded batches.
"""

from collections import Counter
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji import jobs, wiring
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.stores.core import FrappeJobRunStore
from ai_munimji.tests.helpers import FakeStock, empty_store_tables
from ai_munimji.tests.world.parallel import on_own_connections

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"
SETTING_FIELDS = ("enabled", "min_qty", "min_days_cover", "stock_alerts")
LOW = (1, 3, 4, 7, 10)  # of 12 items


class RealCommits(IntegrationTestCase):
	"""A test that commits, as the run does: what it sets up is visible to other connections, and is removed again."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		page = frappe.get_doc(SETTINGS)
		cls.before = {f: page.get(f) for f in SETTING_FIELDS}
		page.enabled, page.min_qty, page.min_days_cover, page.stock_alerts = 1, 10, 0, 0
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
		frappe.db.commit()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		empty_store_tables()
		frappe.db.commit()

	def run_check(self, erp, **kwargs):
		kwargs.setdefault(
			"batch_seconds", None
		)  # the tests count batches by items; the clock's own cut has its test below
		with mock.patch.object(jobs, "system_erp", lambda company=None: erp):
			return jobs.run_stock_check(**kwargs)

	def waiting_items(self) -> list[str]:
		frappe.db.commit()  # a fresh look at what is committed
		return sorted(frappe.get_all(REQUEST, filters={"status": "pending"}, pluck="item_code"))

	def job_run(self) -> dict:
		frappe.db.commit()
		return frappe_core_stores(system=True).jobs.get(jobs.STOCK_CHECK)

	def progress(self) -> str | None:
		frappe.db.commit()
		return frappe.db.get_value("Munimji Job Run", jobs.STOCK_CHECK, "progress")


class TestTheRunInBatches(RealCommits):
	def test_the_requests_are_the_same_whether_the_run_is_cut_into_batches_or_not(self):
		erp = FakeStock(12, LOW)
		wanted = sorted(erp.codes[i] for i in LOW)
		report = self.run_check(erp, batch_size=3)
		self.assertTrue(report["ran"], report)
		self.assertEqual(self.waiting_items(), wanted)
		empty_store_tables()
		frappe.db.commit()
		self.run_check(erp, batch_size=10_000)
		self.assertEqual(self.waiting_items(), wanted, "one batch for everything gives the same requests")

	def test_every_batch_is_committed_and_the_progress_is_seen_from_another_connection(self):
		erp = FakeStock(12, LOW)
		seen: list[str | None] = []
		real_commit = jobs.commit

		def commit_and_look():
			real_commit()
			seen.append(
				on_own_connections(
					"Administrator",
					[lambda: frappe.db.get_value("Munimji Job Run", jobs.STOCK_CHECK, "progress")],
				)[0]
			)

		with mock.patch.object(jobs, "commit", commit_and_look):
			self.run_check(erp, batch_size=5)
		self.assertEqual(
			[s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]],
			[
				"Starting",
				"Worked out the settings of 5 of 12 items",
				"Worked out the settings of 10 of 12 items",
				"Worked out the settings of 12 of 12 items",
				"Read and analysed 5 of 12 items",
				"Read and analysed 10 of 12 items",
				"Read and analysed 12 of 12 items",
				"Looked at 5 of 12 analysed items for requests to raise",
				"Looked at 10 of 12 analysed items for requests to raise",
				"Looked at 12 of 12 analysed items for requests to raise",
			],
			"after each commit another connection sees how far the run has got",
		)
		self.assertEqual(self.progress(), "Finished")
		self.assertEqual(self.job_run()["last_ok"], 1)

	def test_the_raising_stage_is_also_committed_by_the_clock_so_that_a_person_waits_a_second_at_most(self):
		erp = FakeStock(12, LOW)
		texts: list[str] = []
		real_progress = FrappeJobRunStore.progress

		def noting(self, job, text):
			texts.append(text)
			return real_progress(self, job, text)

		with mock.patch.object(FrappeJobRunStore, "progress", noting):
			self.run_check(
				erp, batch_size=10_000, batch_seconds=0
			)  # a batch of ten thousand items, but the clock says "now" after every item
		raising = [t for t in texts if t.startswith("Looked at")]
		self.assertEqual(len(raising), 12, "one commit after each of the 12 items raised for")
		reading = [t for t in texts if t.startswith("Read and analysed")]
		self.assertEqual(
			reading,
			["Read and analysed 12 of 12 items"],
			"reading writes nothing and is cut by the count only",
		)
		self.assertEqual(
			jobs.BATCH_SECONDS,
			0.5,
			"the job's own default: the longest a batch of requests is held before it is committed",
		)

	def test_the_lease_is_renewed_after_every_batch(self):
		erp = FakeStock(12, LOW)
		renewals = mock.Mock(wraps=locks.renew)
		with mock.patch.object(locks, "renew", renewals):
			self.run_check(erp, batch_size=4)
		self.assertEqual(
			renewals.call_count,
			1 + 3 + 3 + 3,
			"once at the start, and three batches each of planning, reading and raising",
		)
		names = {c.args[0] for c in renewals.call_args_list}
		self.assertEqual(names, {jobs.STOCK_CHECK})

	def test_a_run_that_dies_between_batches_keeps_the_earlier_ones_and_run_again_makes_each_request_once(
		self,
	):
		erp = FakeStock(12, LOW)
		wanted = sorted(erp.codes[i] for i in LOW)
		calls = []
		real_renew = locks.renew

		def die_at_the_second_batch_of_raising(name, holder, minutes):
			calls.append(name)
			if (
				len(calls) == 1 + 3 + 3 + 2
			):  # the start, three batches of planning and three of reading, and then the second batch of raising: before its commit
				raise RuntimeError("the worker was killed")
			real_renew(name, holder, minutes)

		with (
			mock.patch.object(locks, "renew", die_at_the_second_batch_of_raising),
			self.assertRaises(RuntimeError),
		):
			self.run_check(erp, batch_size=4)
		half = self.waiting_items()
		self.assertTrue(
			0 < len(half) < len(wanted), f"the first batch of raising is kept, the second is not: {half}"
		)
		row = self.job_run()
		self.assertEqual((row["last_ok"], row["failures"]), (0, 1))
		self.assertIn("the worker was killed", row["last_error"])
		self.assertEqual(
			self.progress(),
			"Looked at 4 of 12 analysed items for requests to raise",
			"it says where it got to",
		)

		report = self.run_check(erp, batch_size=4)
		self.assertTrue(report["ran"], "the lease was given back when the first run died")
		self.assertEqual(self.waiting_items(), wanted, "every low item has a request")
		self.assertEqual(max(Counter(self.waiting_items()).values()), 1, "and none has two")
		self.assertEqual(
			report["alerts"], len(wanted) - len(half), "the second run raised only what the first had not"
		)
		self.assertEqual((self.job_run()["last_ok"], self.progress()), (1, "Finished"))

	def test_the_proposing_stage_is_safe_to_repeat_too_each_approved_reorder_gets_one_proposal(self):
		erp = FakeStock(12, LOW)
		self.run_check(erp, batch_size=4)  # five requests to start a reorder
		services = wiring.build(erp, frappe_core_stores())
		for name in frappe.get_all(
			REQUEST, filters={"status": "pending", "kind": "inventory.reorder"}, pluck="name"
		):
			services.approvals.decide(name, "approve", wiring.actor_for("Administrator"), "desk")
		frappe.db.commit()
		calls = []
		real_renew = locks.renew

		def die_at_the_second_batch_of_proposing(name, holder, minutes):
			calls.append(name)
			if (
				len(calls) == 1 + 6 + 6 + 6 + 2
			):  # the start, six batches of two items each of planning, reading and raising, and the second batch of proposing: before its commit
				raise RuntimeError("the worker was killed")
			real_renew(name, holder, minutes)

		with (
			mock.patch.object(locks, "renew", die_at_the_second_batch_of_proposing),
			self.assertRaises(RuntimeError),
		):
			self.run_check(erp, batch_size=2)
		frappe.db.commit()

		def proposals():
			return sorted(
				frappe.get_all(
					REQUEST, filters={"status": "pending", "kind": "procurement.po"}, pluck="item_code"
				)
			)

		self.assertEqual(len(proposals()), 2, "the first batch of two is kept, the second is not")
		report = self.run_check(erp, batch_size=2)
		self.assertTrue(report["ran"])
		self.assertEqual(
			proposals(), sorted(erp.codes[i] for i in LOW), "one proposal for every approved reorder"
		)
		self.assertEqual(max(Counter(proposals()).values()), 1)
		self.assertEqual(
			report["proposals"], len(LOW) - 2, "the second run proposed only what the first had not"
		)

	def test_a_run_whose_lease_was_taken_by_another_stops_and_leaves_the_other_its_lease(self):
		erp = FakeStock(12, LOW)
		calls = []
		real_renew = locks.renew

		def another_run_takes_the_lease_after_two_batches(name, holder, minutes):
			calls.append(name)
			if (
				len(calls) == 3
			):  # another worker, on its own connection, takes the lease (as it may once this one's has run out) and commits
				until = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=5)
				on_own_connections(
					"Administrator",
					[
						lambda: frappe.db.set_value(
							"Munimji Lock", locks.lease_name(name), {"holder": "another-run", "until": until}
						)
					],
				)
			real_renew(name, holder, minutes)

		with (
			mock.patch.object(locks, "renew", another_run_takes_the_lease_after_two_batches),
			self.assertRaises(locks.LeaseLost),
		):
			self.run_check(erp, batch_size=4)
		frappe.db.commit()
		self.assertEqual(
			frappe.db.get_value("Munimji Lock", locks.lease_name(jobs.STOCK_CHECK), "holder"),
			"another-run",
			"it did not free what is not its own",
		)
		self.assertEqual(self.waiting_items(), [], "it stopped while still reading: nothing was raised")


class TestTheScheduledEntryPutsTheRunOnTheLongQueue(IntegrationTestCase):
	def test_with_watch_stock_on_the_run_is_queued_on_the_long_queue_with_a_long_timeout_once(self):
		with (
			mock.patch.object(frappe, "get_cached_doc", return_value=frappe._dict(enabled=1)),
			mock.patch.object(frappe, "enqueue") as enqueue,
		):
			self.assertEqual(jobs.check_stock(), 0)
		enqueue.assert_called_once_with(
			"ai_munimji.jobs.run_stock_check",
			queue="long",
			timeout=jobs.RUN_TIMEOUT,
			job_id=jobs.QUEUE_JOB_ID,
			deduplicate=True,
		)
		self.assertGreater(
			jobs.RUN_TIMEOUT,
			1500,
			"longer than the long queue's own default of 25 minutes, which a large site's run may need",
		)

	def test_with_watch_stock_off_nothing_is_queued(self):
		with (
			mock.patch.object(frappe, "get_cached_doc", return_value=frappe._dict(enabled=0)),
			mock.patch.object(frappe, "enqueue") as enqueue,
		):
			self.assertEqual(jobs.check_stock(), 0)
		enqueue.assert_not_called()

	def test_every_stage_the_engine_reports_has_words(self):
		self.assertTrue(
			{"starting", "planning", "checking", "raising", "proposing", "sealing", "finished"}
			<= set(jobs.PROGRESS)
		)
		for words in jobs.PROGRESS.values():
			words.format(done="1", total="2")  # every text can be filled in


class TestTheSealIsSweptInBoundedBatches(RealCommits):
	def closed_requests(self, n: int):
		core = frappe_core_stores(system=True)
		for i in range(n):
			core.approvals.insert(
				f"close-{i}", "procurement.po", "{}", None, None, f"2026-10-16T08:{i:02d}:00+00:00", None
			)
			core.approvals.decide_if_pending(
				f"close-{i}", '{"action": "approve"}', f"2026-10-16T09:{i:02d}:00+00:00"
			)
		frappe.db.commit()
		return core

	def services(self):
		return wiring.build(FakeStock(1), frappe_core_stores(system=True))

	def test_a_backlog_is_sealed_a_batch_at_a_time_until_nothing_is_left(self):
		self.closed_requests(7)
		services = self.services()
		sweeps = mock.Mock(wraps=services.audit.sweep)
		services.audit.sweep = sweeps
		checkpoint = jobs.Checkpoint("holder", frappe_core_stores(system=True).jobs)
		with (
			mock.patch("ai_munimji.stores.core.SEAL_BATCH", 3),
			mock.patch.object(jobs.locks, "renew"),
			mock.patch.object(FrappeJobRunStore, "progress"),
		):
			self.assertEqual(jobs.seal_what_is_new(services, checkpoint), 7)
		self.assertEqual(sweeps.call_count, 4, "three batches (3, 3, 1) and a look that finds nothing")
		self.assertTrue(services.audit.verify()["ok"])
		self.assertEqual(frappe_core_stores(system=True).audit.unsealed_count(), 0)

	def test_a_run_seals_no_more_than_its_cap_and_the_next_run_goes_on(self):
		self.closed_requests(7)
		services = self.services()
		checkpoint = jobs.Checkpoint("holder", frappe_core_stores(system=True).jobs)
		with (
			mock.patch("ai_munimji.stores.core.SEAL_BATCH", 3),
			mock.patch.object(jobs, "MAX_SEAL_SWEEPS", 2),
			mock.patch.object(jobs.locks, "renew"),
			mock.patch.object(FrappeJobRunStore, "progress"),
		):
			self.assertEqual(jobs.seal_what_is_new(services, checkpoint), 6)
			self.assertEqual(frappe_core_stores(system=True).audit.unsealed_count(), 1)
			self.assertEqual(jobs.seal_what_is_new(services, checkpoint), 1)
		self.assertTrue(services.audit.verify()["ok"])
