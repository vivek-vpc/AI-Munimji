"""The database setting innodb_snapshot_isolation: the app cannot change the server, so it says so (after install and migrate, and at the top of the Settings page) and it keeps the sentence a
person reads on a simultaneous press plain.

ON warns, OFF is silent, and a setting that cannot be read is silent too and fails nothing.
"""

from types import SimpleNamespace
from unittest import mock

import frappe
from ai_munimji_engine.core.approvals.models import DecisionResult
from frappe.tests import IntegrationTestCase

from ai_munimji import api, dbcheck, install, wiring
from ai_munimji.tests.helpers import make_user

SETTINGS = "AI Munimji Settings"


def rows(value: str):
	return (("innodb_snapshot_isolation", value),)


class TestReadingTheSetting(IntegrationTestCase):
	def test_on_is_true_and_off_is_false(self):
		for value, expected in (("ON", True), ("on", True), ("1", True), ("OFF", False), ("0", False)):
			with mock.patch.object(frappe.db, "sql", return_value=rows(value)):
				self.assertIs(dbcheck.snapshot_isolation_is_on(), expected, value)

	def test_a_setting_that_cannot_be_read_says_nothing_and_fails_nothing(self):
		with mock.patch.object(frappe.db, "sql", side_effect=Exception("(1227, 'Access denied')")):
			self.assertIsNone(dbcheck.snapshot_isolation_is_on(), "no right to run the statement")
		with mock.patch.object(frappe.db, "sql", return_value=()):
			self.assertIsNone(dbcheck.snapshot_isolation_is_on(), "a server that has no such variable")
		with mock.patch.object(frappe.db, "db_type", "postgres"), mock.patch.object(frappe.db, "sql") as sql:
			self.assertIsNone(dbcheck.snapshot_isolation_is_on(), "another database")
			sql.assert_not_called()

	def test_the_real_database_answers_a_yes_or_a_no(self):
		self.assertIn(dbcheck.snapshot_isolation_is_on(), (True, False))
		try:
			frappe.db.sql("SET SESSION innodb_snapshot_isolation=ON")
		except Exception:
			self.skipTest("this server does not let a session switch the setting")
		try:
			self.assertIs(
				dbcheck.snapshot_isolation_is_on(), True, "read back from the server while it is ON"
			)
		finally:
			frappe.db.sql("SET SESSION innodb_snapshot_isolation=OFF")
		self.assertIs(dbcheck.snapshot_isolation_is_on(), False, "and while it is OFF")


class TestSayingSo(IntegrationTestCase):
	def test_after_install_and_migrate_on_warns_without_stopping_anything(self):
		with (
			mock.patch.object(dbcheck, "snapshot_isolation_is_on", return_value=True),
			mock.patch("click.secho") as say,
			mock.patch.object(frappe, "logger") as logger,
		):
			install.check_database()  # returns: it never raises
		say.assert_called_once()
		self.assertIn("innodb_snapshot_isolation", say.call_args.args[0])
		logger.return_value.warning.assert_called_once_with(dbcheck.warning())

	def test_after_install_and_migrate_off_and_unreadable_are_silent(self):
		for state in (False, None):
			with (
				mock.patch.object(dbcheck, "snapshot_isolation_is_on", return_value=state),
				mock.patch("click.secho") as say,
				mock.patch.object(frappe, "logger") as logger,
			):
				install.check_database()
			say.assert_not_called()
			logger.assert_not_called()

	def test_the_hooks_run_the_check_after_install_and_after_migrate(self):
		for hook in ("after_install", "after_migrate"):
			self.assertIn("ai_munimji.install.check_database", frappe.get_hooks(hook))

	def test_the_settings_page_carries_the_warning_only_while_it_is_on(self):
		page = frappe.get_doc(SETTINGS)
		with mock.patch.object(dbcheck, "snapshot_isolation_is_on", return_value=True):
			page.onload()
		self.assertEqual(page.get("__onload").snapshot_isolation_warning, dbcheck.warning())
		for state in (False, None):
			fresh = frappe.get_doc(SETTINGS)
			with mock.patch.object(dbcheck, "snapshot_isolation_is_on", return_value=state):
				fresh.onload()
			self.assertFalse(
				(fresh.get("__onload") or {}).get("snapshot_isolation_warning"), f"silent when {state}"
			)

	def test_the_page_script_shows_it_at_the_top(self):
		script = frappe.get_app_path(
			"ai_munimji", "ai_munimji", "doctype", "ai_munimji_settings", "ai_munimji_settings.js"
		)
		text = open(script, encoding="utf-8").read()
		self.assertIn("snapshot_isolation_warning", text)
		self.assertIn("set_headline_alert", text)


class TestTheSentenceAPersonReads(IntegrationTestCase):
	"""A lost race or a database that refuses the second answer reads as one plain sentence: no database words, no numbers, no trace."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"busy_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		frappe.set_user(make_user("busy.approver@example.com", ("Munimji Approver",)))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)

	def answer_with(self, decide):
		services = SimpleNamespace(approvals=SimpleNamespace(decide=decide))
		with (
			mock.patch.object(wiring, "person_services", return_value=services),
			mock.patch.object(wiring, "actor_for", return_value=None),
			mock.patch.object(frappe.db, "rollback") as rollback,
		):
			return api.answer("abc", "approve"), rollback

	def assertPlain(self, message: str):
		for word in (
			"1020",
			"1305",
			"SAVEPOINT",
			"Traceback",
			"OperationalError",
			"Record has changed",
			"Status:",
		):
			self.assertNotIn(word, message)
		self.assertTrue(message.endswith("."), message)
		self.assertIn("Nothing was changed", message)
		self.assertIn("Reload the page", message)

	def test_a_database_that_refuses_the_second_answer(self):
		def refuse(*args, **kwargs):
			raise frappe.QueryDeadlockError("(1020, 'Record has changed since last read in table')")

		out, rollback = self.answer_with(refuse)
		self.assertEqual((out["ok"], out["status"]), (False, "busy"))
		self.assertPlain(out["message"])
		rollback.assert_called_once()

	def test_a_lock_that_was_held_too_long(self):
		def wait(*args, **kwargs):
			raise frappe.QueryTimeoutError("(1205, 'Lock wait timeout exceeded')")

		out, _rollback = self.answer_with(wait)
		self.assertEqual((out["ok"], out["status"]), (False, "busy"))
		self.assertPlain(out["message"])

	def test_what_the_engine_says_when_it_lost_the_race_or_failed_is_replaced(self):
		engine_words = (
			DecisionResult(
				ok=False,
				status="error",
				message="Could not apply your decision ((1305, 'SAVEPOINT munimji_e0 does not exist')). Nothing was changed - please try again.",
			),
			DecisionResult(ok=False, status="pending", message="Status: pending."),
		)
		for result in engine_words:
			out, _rollback = self.answer_with(lambda *a, **k: result)
			self.assertEqual((out["ok"], out["status"]), (False, "busy"), result.status)
			self.assertPlain(out["message"])

	def test_the_engines_own_clear_refusals_and_answers_pass_through_unchanged(self):
		for result in (
			DecisionResult(
				ok=False, status="already_decided", message="Already answered: Create order (by someone)."
			),
			DecisionResult(
				ok=False, status="forbidden", message="You are not allowed to answer approval requests."
			),
			DecisionResult(ok=True, status="decided", message="Recorded: Create order."),
		):
			out, _rollback = self.answer_with(lambda *a, **k: result)
			self.assertEqual(
				(out["ok"], out["status"], out["message"]), (result.ok, result.status, result.message)
			)

	def test_the_order_client_says_the_same_kind_of_thing_when_its_lock_is_busy(self):
		from ai_munimji.erp_client import FrappeERPClient

		client = FrappeERPClient()
		with (
			mock.patch.object(client, "_company", return_value="Any Company"),
			mock.patch.object(client, "_acting_is_me", return_value=None),
			mock.patch.object(
				client, "_hold", side_effect=frappe.QueryTimeoutError("(1205, 'Lock wait timeout')")
			),
		):
			result = client._make("Purchase Order", {}, "REF-1", "someone", "purchase order", None)
		self.assertFalse(result.ok)
		self.assertEqual(
			result.error,
			"Another press for this request is still being handled. Wait a moment and look at the purchase order before pressing again.",
		)
		for word in ("1205", "Lock wait", "Traceback", "Error"):
			self.assertNotIn(word, result.error)
