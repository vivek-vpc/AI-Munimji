"""The "Run the check now" button of the Settings page, and the status block beside it (Group 2, F4 of the production-readiness review).

Only a Munimji Manager or a System Manager may press it; it queues the stock check at once, refuses a second press while a check is queued or running (with a plain sentence), and the
page says when the last check ran, how far it got and how many requests it made. The refusal of a Viewer and of an Approver who is not a Manager is also asked over HTTP, as real people
(dev/scripts/permissions_http.py).
"""

from unittest import mock

import frappe
from frappe.utils.background_jobs import JobStatus

from ai_munimji import api, jobs
from ai_munimji.last_run import STOCK_CHECK
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.tests.helpers import make_user
from ai_munimji.tests.test_vendor_comparison import FakeBuyer, FlowCase


class PressingTheButton(FlowCase):
	def queued_checks(self) -> list:
		return [
			c
			for c in self.enqueued.call_args_list
			if c.args and c.args[0] == "ai_munimji.jobs.run_stock_check_now"
		]

	def press(self, user: str | None = None, state: str = "idle") -> dict:
		frappe.set_user(user or self.manager)
		try:
			with mock.patch.object(jobs, "check_state", return_value=state):
				return api.run_check_now()
		finally:
			frappe.set_user("Administrator")

	def test_a_manager_queues_the_check_on_the_long_queue_under_the_checks_job_id(self):
		said = self.press()
		self.assertEqual((said["ok"], said["status"]), (True, "queued"), said)
		self.enqueued.assert_called_once_with(
			"ai_munimji.jobs.run_stock_check_now",
			queue="long",
			timeout=jobs.RUN_TIMEOUT,
			job_id=jobs.QUEUE_JOB_ID,
			deduplicate=True,
		)
		self.assertIn("queued", said["message"])

	def test_a_system_manager_may_press_it_too(self):
		boss = make_user("flow.boss@example.com", ("System Manager",))
		self.assertEqual(self.press(boss)["status"], "queued")
		self.assertEqual(self.press("Administrator")["status"], "queued")

	def test_a_viewer_and_an_approver_who_is_not_a_manager_are_refused_and_nothing_is_queued(self):
		for user in (self.viewer, self.approver, make_user("flow.nobody@example.com", ())):
			with self.assertRaises(frappe.PermissionError, msg=user):
				self.press(user)
		self.assertEqual(self.queued_checks(), [])

	def test_a_second_press_while_a_check_is_queued_or_running_is_refused_in_a_plain_sentence(self):
		waiting = self.press(state="queued")
		self.assertEqual((waiting["ok"], waiting["status"]), (False, "queued_already"))
		self.assertEqual(
			waiting["message"],
			"A stock check is already waiting to start. Nothing more was queued: wait for it to finish.",
		)
		running = self.press(state="running")
		self.assertEqual((running["ok"], running["status"]), (False, "running"))
		self.assertIn("A stock check is running now.", running["message"])
		self.assertTrue(running["busy"])
		self.assertEqual(self.queued_checks(), [])

	def test_two_presses_at_the_same_moment_queue_one(self):
		self.enqueued.return_value = None  # Frappe's deduplication: a job with this id is queued already
		said = self.press()
		self.assertEqual((said["ok"], said["status"]), (False, "queued_already"))

	def test_nothing_is_queued_while_watch_stock_is_off(self):
		page = frappe.get_doc("AI Munimji Settings")
		page.enabled = 0
		page.save()
		said = self.press()
		self.assertEqual((said["ok"], said["status"]), (False, "off"))
		self.assertEqual(
			said["message"],
			"Watch stock is switched off, so no check can run. Switch it on and save the page first.",
		)
		self.assertEqual(self.queued_checks(), [])


class WhatCountsAsQueuedOrRunning(FlowCase):
	def state(self, status, held=False) -> str:
		with (
			mock.patch("frappe.utils.background_jobs.get_job_status", return_value=status),
			mock.patch.object(locks, "held", return_value=held),
		):
			return jobs.check_state()

	def test_the_queue_and_the_lease_are_both_asked(self):
		self.assertEqual(self.state(JobStatus.QUEUED), "queued")
		self.assertEqual(self.state(JobStatus.STARTED), "running")
		self.assertEqual(
			self.state(None, held=True),
			"running",
			"a check started from the command line holds the lease without being queued",
		)
		self.assertEqual(self.state(JobStatus.FINISHED), "idle")
		self.assertEqual(self.state(None), "idle")

	def test_a_lease_that_nobody_holds_or_that_has_run_out_is_not_a_running_check(self):
		self.assertFalse(locks.held("stock_check"))
		with free_lease_row("someone", minutes=5):
			self.assertTrue(locks.held("stock_check"))
		with free_lease_row("someone", minutes=-5):
			self.assertFalse(locks.held("stock_check"), "its time ran out: the holder is taken for dead")


class free_lease_row:
	"""Hold the stock check's lease for a while (a negative time: it ran out), for the length of a with block."""

	def __init__(self, holder: str, minutes: float):
		self.holder, self.minutes = holder, minutes

	def __enter__(self):
		from datetime import timedelta

		from frappe.utils import now_datetime

		row = frappe.get_doc("Munimji Lock", locks.lease_name("stock_check"), for_update=True)
		row.holder, row.until = self.holder, now_datetime() + timedelta(minutes=self.minutes)
		row.flags.munimji_store = True
		row.save()

	def __exit__(self, *exc):
		row = frappe.get_doc("Munimji Lock", locks.lease_name("stock_check"), for_update=True)
		row.holder, row.until = None, None
		row.flags.munimji_store = True
		row.save()


class TheQueuedJob(FlowCase):
	def test_it_runs_as_administrator_whoever_queued_it(self):
		seen = []
		frappe.set_user(self.manager)
		try:
			with mock.patch.object(
				jobs, "run_stock_check", lambda: seen.append(frappe.session.user) or {"ran": True}
			):
				jobs.run_stock_check_now()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(seen, ["Administrator"])


class TheStatusBlock(FlowCase):
	def status(self, user: str | None = None, state: str = "idle") -> dict:
		frappe.set_user(user or self.manager)
		try:
			with mock.patch.object(jobs, "check_state", return_value=state):
				return api.check_status()
		finally:
			frappe.set_user("Administrator")

	def rows(self, **kwargs) -> dict:
		return dict(map(tuple, self.status(**kwargs)["rows"]))

	def test_before_any_check_it_says_so(self):
		self.assertEqual(self.rows(), {"Last check": "The stock check has not run yet."})

	def test_after_a_check_it_says_when_how_far_it_got_and_how_many_requests_it_made(self):
		self.erp = FakeBuyer(count=3, low=(0, 1))
		report = self.scheduled_check()
		self.assertEqual(report["requests"], 2)
		rows = self.rows()
		self.assertEqual(list(rows), ["Last check", "How far it got", "Requests it made"])
		self.assertRegex(
			rows["Last check"],
			r"^\d{1,2} \w{3} \d{4}, \d\d:\d\d \(finished \d{1,2} \w{3} \d{4}, \d\d:\d\d\)$",
		)
		self.assertEqual(rows["How far it got"], "Finished")
		self.assertEqual(rows["Requests it made"], "2")

	def test_a_check_that_made_nothing_says_zero(self):
		self.erp = FakeBuyer(count=2, low=())
		self.scheduled_check()
		self.assertEqual(self.rows()["Requests it made"], "0")

	def test_a_check_that_failed_says_how_far_it_got_and_what_went_wrong(self):
		# written as run_stock_check writes a failure (its own rollback and commit cannot be run inside a test's transaction; test_batched_run.py runs a failing check with real commits)
		stores = frappe_core_stores(system=True)
		stores.jobs.started(STOCK_CHECK, "2026-11-11T06:00:00+00:00")
		stores.jobs.progress(STOCK_CHECK, "Looked at 400 of 5,000 analysed items for requests to raise")
		stores.jobs.finished(
			STOCK_CHECK, "2026-11-11T06:03:00+00:00", False, "RuntimeError: the database went away"
		)
		rows = self.rows()
		self.assertEqual(list(rows), ["Last check", "How far it got", "What went wrong"])
		self.assertEqual(rows["What went wrong"], "RuntimeError: the database went away")
		self.assertEqual(
			rows["How far it got"], "Looked at 400 of 5,000 analysed items for requests to raise"
		)

	def test_while_a_check_is_running_the_page_says_how_far_it_has_got(self):
		self.scheduled_check()
		running = self.status(state="running")
		self.assertTrue(running["busy"])
		self.assertEqual(dict(map(tuple, running["rows"]))["Now"], "A stock check is running.")
		queued = self.status(state="queued")
		self.assertTrue(queued["busy"])
		self.assertEqual(
			dict(map(tuple, queued["rows"]))["Now"], "A stock check is waiting for a worker to start it."
		)

	def test_the_block_is_for_the_people_who_may_open_the_settings_page(self):
		self.scheduled_check()
		self.assertIn("Last check", self.rows())
		for user in (self.viewer, self.approver):
			with self.assertRaises(frappe.PermissionError, msg=user):
				self.status(user)
