"""The stock check's scheduled job follows the Settings page and survives a migrate; the Approvers are told once when a request is made.

The job is a Scheduled Job Type linked to a Scheduler Event (schedule.py says why it is not a hook). What a tick then does, with real stock, is in tests/world/test_flow.py.
"""

import frappe
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import sync_jobs
from frappe.tests import IntegrationTestCase

from ai_munimji import install, schedule
from ai_munimji.tests.helpers import empty_store_tables, make_request, make_user

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"


class Rolled(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"schedule_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)
		frappe.clear_document_cache(SETTINGS, SETTINGS)


class TestTheScheduledJob(Rolled):
	def job(self):
		return frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD})

	def save_page(self, enabled: int, cron: str):
		page = frappe.get_doc(SETTINGS)
		page.enabled, page.check_cron = enabled, cron
		page.save()

	def test_the_job_follows_what_the_page_holds(self):
		self.save_page(0, "0 6 * * *")
		job = self.job()
		self.assertEqual(
			(job.frequency, job.cron_format, job.stopped, job.method),
			("Cron", "0 6 * * *", 1, schedule.METHOD),
			"Watch stock is off: the job exists and is stopped",
		)
		self.assertTrue(
			job.scheduler_event, "it stands on a Scheduler Event, which is what a migrate leaves alone"
		)
		self.save_page(1, "30 7 * * 1")
		job = self.job()
		self.assertEqual((job.cron_format, job.stopped), ("30 7 * * 1", 0), "on, at the page's time")
		self.save_page(0, "30 7 * * 1")
		self.assertEqual(self.job().stopped, 1, "off again stops it")

	def test_an_edited_schedule_survives_a_migrate(self):
		self.save_page(1, "15 5 * * *")
		sync_jobs()  # what bench migrate does with the jobs that hooks declare
		install.make_locks()
		install.make_schedule()  # and the app's own after_migrate hooks
		install.make_notification()
		job = self.job()
		self.assertEqual(
			(job.cron_format, job.stopped), ("15 5 * * *", 0), "the page's time and switch are kept"
		)
		self.assertEqual(frappe.db.count("Scheduled Job Type", {"method": schedule.METHOD}), 1)
		self.assertEqual(
			frappe.db.count(
				"Scheduler Event", {"scheduled_against": schedule.AGAINST, "method": schedule.METHOD}
			),
			1,
		)

	def test_a_migrate_makes_the_job_again_from_the_page_if_it_was_lost(self):
		self.save_page(1, "20 4 * * *")
		frappe.delete_doc("Scheduled Job Type", self.job().name, force=True)
		install.make_schedule()
		job = self.job()
		self.assertEqual((job.cron_format, job.stopped), ("20 4 * * *", 0))

	def test_the_negative_control_a_job_nothing_stands_behind_is_deleted_by_a_migrate(self):
		"""Why the job is not simply declared or made by hand: Frappe's migrate deletes a Scheduled Job Type that no hook, Server Script or Scheduler Event stands behind."""
		method = "ai_munimji.install.make_locks"
		frappe.get_doc({"doctype": "Scheduled Job Type", "method": method, "frequency": "Daily"}).insert()
		self.save_page(1, "0 6 * * *")
		sync_jobs()
		self.assertFalse(frappe.db.exists("Scheduled Job Type", {"method": method}))
		self.assertTrue(frappe.db.exists("Scheduled Job Type", {"method": schedule.METHOD}))

	def test_a_manager_who_holds_no_right_on_job_records_can_still_set_the_schedule(self):
		manager = make_user("schedule.manager@example.com", ("Munimji Manager",))
		frappe.set_user(manager)
		self.assertFalse(
			frappe.has_permission("Scheduled Job Type", "write"),
			"the premise: this person has no right on Frappe's job records",
		)
		self.save_page(1, "45 8 * * *")
		frappe.set_user("Administrator")
		job = self.job()
		self.assertEqual((job.cron_format, job.stopped), ("45 8 * * *", 0))

	def test_uninstall_takes_the_job_and_its_event_out(self):
		from ai_munimji import uninstall

		self.save_page(1, "0 6 * * *")
		uninstall.before_uninstall()
		self.assertFalse(frappe.db.exists("Scheduled Job Type", {"method": schedule.METHOD}))
		self.assertFalse(frappe.db.exists("Scheduler Event", {"scheduled_against": schedule.AGAINST}))
		self.assertFalse(frappe.db.exists("Notification", install.NOTIFICATION))


class TestTheCleanUpJob(Rolled):
	"""The logs are cleaned up once a day by a job that follows "Keep logs for (days)": running while it is a positive number, stopped while it is 0."""

	def job(self):
		return frappe.get_doc("Scheduled Job Type", {"method": schedule.CLEAN_UP})

	def save_page(self, keep_logs_days: int):
		page = frappe.get_doc(SETTINGS)
		page.keep_logs_days = keep_logs_days
		page.save()

	def test_it_is_a_daily_job_standing_on_a_scheduler_event_and_running_with_the_default_days(self):
		install.make_schedule()  # what install and every migrate do
		job = self.job()
		self.assertEqual(
			(job.frequency, job.stopped, job.method, job.create_log),
			("Daily Long", 0, "ai_munimji.retention.clean_up", 1),
			"every day, running: the page holds the default of 90 days",
		)
		self.assertTrue(
			job.scheduler_event, "it stands on a Scheduler Event, which is what a migrate leaves alone"
		)

	def test_it_is_off_unless_the_days_are_a_positive_number(self):
		self.save_page(0)
		self.assertEqual(self.job().stopped, 1, "0 keeps everything: nothing is cleaned up by itself")
		self.save_page(30)
		self.assertEqual(self.job().stopped, 0)
		self.save_page(0)
		self.assertEqual(self.job().stopped, 1)

	def test_a_page_that_holds_no_number_means_the_default_and_runs(self):
		self.assertEqual(frappe.get_doc("Scheduled Job Type", schedule.sync_clean_up(None)).stopped, 0)

	def test_it_survives_a_migrate_and_is_made_again_if_it_was_lost(self):
		self.save_page(0)
		sync_jobs()  # what bench migrate does with the jobs that hooks declare
		install.make_schedule()  # and the app's own after_migrate hooks
		self.assertEqual(
			(self.job().stopped, frappe.db.count("Scheduled Job Type", {"method": schedule.CLEAN_UP})), (1, 1)
		)
		frappe.delete_doc("Scheduled Job Type", self.job().name, force=True)
		install.make_schedule()
		self.assertEqual(self.job().stopped, 1, "made again from the page, which says 0")
		self.assertEqual(
			frappe.db.count(
				"Scheduler Event", {"scheduled_against": schedule.AGAINST, "method": schedule.CLEAN_UP}
			),
			1,
		)

	def test_the_stock_checks_job_is_not_disturbed(self):
		before = frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD}).as_dict()
		self.save_page(30)
		after = frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD}).as_dict()
		for key in ("frequency", "cron_format", "stopped", "scheduler_event"):
			self.assertEqual(before[key], after[key], key)

	def test_a_manager_who_holds_no_right_on_job_records_can_set_it(self):
		frappe.set_user(make_user("cleanup.manager@example.com", ("Munimji Manager",)))
		self.save_page(0)
		frappe.set_user("Administrator")
		self.assertEqual(self.job().stopped, 1)

	def test_uninstall_takes_it_out_with_its_event(self):
		from ai_munimji import uninstall

		install.make_schedule()
		uninstall.before_uninstall()
		self.assertFalse(frappe.db.exists("Scheduled Job Type", {"method": schedule.CLEAN_UP}))
		self.assertFalse(frappe.db.exists("Scheduler Event", {"method": schedule.CLEAN_UP}))

	def test_what_the_scheduler_runs_deletes_old_logs_and_nothing_a_person_answers_and_not_the_seal(self):
		from datetime import timedelta

		from ai_munimji_engine.core.common import iso, utcnow

		from ai_munimji import jobs
		from ai_munimji.stores import frappe_stock_stores

		self.save_page(30)
		empty_store_tables()
		core = jobs.system_stores()
		stock = frappe_stock_stores(core)
		now = utcnow()

		def ago(days):
			return iso(now - timedelta(days=days))

		core.agents.add_tool_call(ago(100), "agent", "mcp", "tool-old", "{}", True, 1, None, None)
		core.agents.add_tool_call(ago(1), "agent", "mcp", "tool-new", "{}", True, 1, None, None)
		stock.runs.add("run-old", "inventory", ago(100), ago(100), False, "{}")
		stock.runs.add("run-new", "inventory", ago(1), ago(1), False, "{}")
		core.approvals.insert(
			"request", "procurement.po", "{}", None, None, ago(2000), None
		)  # pending, however old
		stock.alerts.insert("alert", "BOLT", "BREACH", 2, ago(2000), "{}", "low", None)
		stock.proposals.insert(
			"proposal", "w", "BOLT", "awaiting", None, None, None, None, None, None, "", ago(2000)
		)
		core.audit.append(ago(2000), "approval", "request", "decided", "d", "0" * 64, "h")

		job = self.job()
		self.assertEqual(job.stopped, 0)
		gone = frappe.get_attr(job.method)()  # the call Frappe's scheduler makes, as Administrator

		self.assertEqual((gone["tool_calls"], gone["agent_runs"]), (1, 1))
		self.assertEqual({r["tool"] for r in core.agents.tool_calls(None, 10)}, {"tool-new"})
		self.assertEqual(set(core.backend.table("agent_runs").names()), {"run-new"})
		for engine_table in ("approvals", "alerts", "proposals", "audit_chain"):
			self.assertEqual(
				len(core.backend.table(engine_table).names()), 1, f"{engine_table} is never touched"
			)


class TestTheNotification(Rolled):
	def test_it_goes_to_the_approvers_on_the_system_channel_only(self):
		note = frappe.get_doc("Notification", install.NOTIFICATION)
		self.assertEqual(
			(note.enabled, note.channel, note.event, note.document_type, note.condition),
			(1, "System Notification", "New", REQUEST, 'doc.status == "pending"'),
		)
		self.assertEqual(
			[r.receiver_by_role for r in note.recipients],
			["Munimji Approver"],
			"the role that answers; no e-mail address",
		)
		self.assertFalse(any(r.cc or r.bcc for r in note.recipients))

	def test_a_new_request_tells_each_approver_once_and_nobody_else(self):
		approver = make_user("note.approver@example.com", ("Munimji Approver",))
		viewer = make_user("note.viewer@example.com", ("Munimji Viewer",))
		empty_store_tables()
		request = make_request("Order bolts")
		logs = frappe.get_all(
			"Notification Log",
			filters={"document_type": REQUEST, "document_name": request.name},
			fields=["for_user", "subject"],
		)
		users = [row.for_user for row in logs]
		self.assertIn(approver, users, "the Approver is told")
		self.assertNotIn(viewer, users, "a Viewer, who cannot answer, is not")
		self.assertEqual(len(users), len(set(users)), f"nobody is told twice: {users}")
		self.assertEqual(logs[0].subject, "Order bolts")

		# the request is changed and looked at again: Frappe's New event does not run again
		doc = frappe.get_doc(REQUEST, request.name)
		doc.flags.munimji_store = True
		doc.status_note = "looked at again"
		doc.save(ignore_permissions=True)
		again = frappe.get_all(
			"Notification Log", filters={"document_type": REQUEST, "document_name": request.name}
		)
		self.assertEqual(len(again), len(logs), "a request that is looked at again is not announced again")
