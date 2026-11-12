"""The address Telegram calls, and the loop that fetches updates when Telegram cannot call (AI Munimji Telegram, A1 and A2).

The webhook is the one method of the app that a stranger can call, so what is shown first is that it does nothing until the call has proved who it is. Then that a call which has is handled as
the person the chat belongs to, that a failure never makes Telegram send the same update for ever, and that the session goes back to Guest. The polling loop handles the same updates through
the same function, one at a time, holds one lease, stops when Telegram is switched off or set to webhook, and queues its successor.
"""

from contextlib import contextmanager
from unittest import mock

import frappe
from werkzeug.test import EnvironBuilder

from ai_munimji.stores import locks
from ai_munimji.telegram import config, inbound, webhook
from ai_munimji.telegram import jobs as telegram_jobs
from ai_munimji.tests.telegram_kit import TOKEN, TelegramCase, message, press
from ai_munimji.tests.test_vendor_comparison import FakeBuyer

HEADER = webhook.HEADER


@contextmanager
def request_with(body, headers: dict | None = None, raw: bytes | None = None):
	"""The request Telegram would make, as the web server hands it to Frappe."""
	builder = EnvironBuilder(
		method="POST", headers=headers or {}, data=raw, json=None if raw is not None else body
	)
	before = getattr(frappe.local, "request", None)
	frappe.local.request = builder.get_request()
	try:
		yield
	finally:
		frappe.local.request = before


class TestTheWebhook(TelegramCase):
	def make_erp(self):
		return FakeBuyer(count=3, low=(0,))

	def setUp(self):
		super().setUp()
		self.connect("alice")
		self.reorder = self.raise_a_reorder()
		self.deliver()
		self.telegram.calls.clear()
		frappe.set_user("Guest")
		self.secret = config.webhook_secret()

	def call(self, body, secret="right", **kwargs):
		headers = {HEADER: self.secret if secret == "right" else secret} if secret else {}
		with request_with(body, headers, **kwargs):
			return webhook.receive()

	def test_a_call_without_the_secret_is_refused_before_anything_is_read(self):
		for secret in (None, "", "wrong", self.secret[:-1], self.secret + "x"):
			with self.assertRaises(frappe.PermissionError, msg=repr(secret)):
				self.call(press("1001", self.reorder, "approve"), secret=secret)
		frappe.set_user("Administrator")
		self.assertIsNone(self.decision_of(self.reorder))
		self.assertEqual(self.telegram.calls, [])

	def test_a_call_is_refused_while_telegram_is_off_even_with_the_right_secret(self):
		secret = self.secret
		self.switch_telegram(False)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			with request_with(press("1001", self.reorder, "approve"), {HEADER: secret}):
				webhook.receive()

	def test_the_secret_is_compared_in_constant_time(self):
		with mock.patch.object(webhook.hmac, "compare_digest", return_value=False) as compared:
			with self.assertRaises(frappe.PermissionError):
				self.call(press("1001", self.reorder, "approve"))
		compared.assert_called_once()

	def test_a_call_with_the_secret_is_handled_as_the_connected_person_and_the_session_goes_back_to_guest(
		self,
	):
		out = self.call(press("1001", self.reorder, "approve"))
		self.assertEqual(out, {"ok": True})
		self.assertEqual(frappe.session.user, "Guest")
		frappe.set_user("Administrator")
		decision = self.decision_of(self.reorder)
		self.assertEqual((decision["actor_id"], decision["channel"]), (self.alice, "telegram"))

	def test_a_stranger_who_writes_through_the_webhook_changes_nothing_and_learns_only_their_id(self):
		self.call(message("9999", "/start"))
		self.assertIn("9999", self.telegram.texts("9999")[0])
		frappe.set_user("Administrator")
		self.assertIsNone(self.decision_of(self.reorder))

	def test_a_body_that_is_not_an_update_is_acknowledged_and_ignored(self):
		for raw in (b"not json", b"[1, 2]", b"null", b""):
			self.assertEqual(self.call(None, raw=raw), {"ok": True}, raw)
		self.assertEqual(self.telegram.calls, [])

	def test_a_body_that_is_far_too_large_is_ignored(self):
		huge = {
			"update_id": 1,
			"message": {
				"text": "x" * (webhook.MAX_BODY + 10),
				"from": {"id": 1001},
				"chat": {"id": 1001, "type": "private"},
			},
		}
		self.assertEqual(self.call(huge), {"ok": True})
		self.assertEqual(self.telegram.calls, [])

	def test_a_failure_while_handling_is_logged_without_the_token_and_telegram_is_still_told_ok(self):
		boom = RuntimeError(f"boom at https://api.telegram.org/bot{TOKEN}/sendMessage with {self.secret}")
		with (
			mock.patch.object(inbound, "handle_update", side_effect=boom),
			mock.patch.object(frappe.db, "rollback") as rolled,
		):
			out = self.call(press("1001", self.reorder, "approve"))
		rolled.assert_called()  # what the failed update did is taken back
		self.assertEqual(out, {"ok": True}, "an answer of anything else makes Telegram send the update again")
		self.assertEqual(frappe.session.user, "Guest")
		frappe.set_user("Administrator")
		[logged] = frappe.get_all(
			"Error Log", filters={"method": ["like", "%update from Telegram%"]}, fields=["error"], limit=1
		)
		self.assertIn("boom at", logged.error)
		self.assertNotIn(TOKEN, logged.error)
		self.assertNotIn(TOKEN.split(":")[1], logged.error)
		self.assertNotIn(self.secret, logged.error)
		self.assertIsNone(self.decision_of(self.reorder))

	def test_the_webhook_is_the_only_method_of_the_app_a_guest_can_call(self):
		from ai_munimji import api
		from ai_munimji.telegram import api as telegram_api

		self.assertIn(webhook.receive, frappe.guest_methods)
		for module in (api, telegram_api):
			for name in dir(module):
				function = getattr(module, name)
				if callable(function) and getattr(function, "__module__", "") == module.__name__:
					self.assertNotIn(function, frappe.guest_methods, f"{module.__name__}.{name}")


class TestPolling(TelegramCase):
	def make_erp(self):
		return FakeBuyer(count=3, low=(0,))

	def setUp(self):
		super().setUp()
		self.switch_telegram(True, mode="Polling")
		self.connect("alice")
		self.reorder = self.raise_a_reorder()
		self.deliver()
		self.telegram.calls.clear()
		self.lease = mock.patch.multiple(
			locks,
			lease=mock.Mock(return_value=True),
			release=mock.Mock(return_value=None),
			renew=mock.Mock(return_value=None),
		)
		self.lease.start()
		mock.patch.object(
			frappe.db, "commit"
		).start()  # the loop keeps what each update did, and takes back a failed one; these tests' own rollback must still take back all of it
		real_rollback = frappe.db.rollback
		mock.patch.object(
			frappe.db,
			"rollback",
			lambda *a, save_point=None, **k: real_rollback(*a, save_point=save_point, **k)
			if save_point
			else None,
		).start()

	def run_the_loop(self, wanted):
		frappe.set_user("Administrator")
		with (
			mock.patch.object(telegram_jobs, "wanted", side_effect=wanted),
			mock.patch.object(telegram_jobs.time, "sleep"),
		):
			return telegram_jobs.poll()

	def test_the_loop_handles_what_telegram_has_waiting_as_the_webhook_would(self):
		self.telegram.updates = [
			press("1001", self.reorder, "approve", update_id=2001),
			message("9999", "/start", update_id=2002),
		]
		out = self.run_the_loop([True, True, False, False])
		self.assertEqual(out, {"ran": True, "handled": 2})
		self.assertEqual(self.decision_of(self.reorder)["actor_id"], self.alice)
		self.assertIn("9999", self.telegram.texts("9999")[0])
		self.assertEqual(
			len(self.telegram.of("deleteWebhook")),
			1,
			"Telegram refuses to hand out updates while a webhook is set",
		)
		[asked] = self.telegram.of("getUpdates")
		self.assertEqual(
			(asked["timeout"], asked["allowed_updates"]),
			(telegram_jobs.LONG_POLL_SECONDS, ["callback_query", "message"]),
		)

	def test_the_place_it_has_got_to_is_kept_where_every_process_sees_it(self):
		self.telegram.updates = [{**press("1001", self.reorder, "details"), "update_id": 3001}]
		self.run_the_loop([True, True, False, False])
		self.run_the_loop([True, True, False, False])
		self.assertEqual(self.telegram.of("getUpdates")[-1]["offset"], 3002)

	def test_an_update_that_fails_costs_that_update_only_and_the_person_is_told(self):
		self.telegram.updates = [
			press("1001", self.reorder, "approve", update_id=4001),
			press("1001", self.reorder, "details", update_id=4002),
		]
		real = inbound.handle_event
		calls = []

		def flaky(channel, event):
			calls.append(event.action)
			if event.action == "approve":
				raise RuntimeError(f"boom {TOKEN}")
			return real(channel, event)

		with mock.patch.object(inbound, "handle_event", flaky):
			out = self.run_the_loop([True, True, False, False])
		self.assertEqual(out["handled"], 1)
		self.assertEqual(calls, ["approve", "details"], "the next update was still handled")
		self.assertIn("could not handle that just now", self.telegram.texts("1001")[-2])
		self.assertIsNone(self.decision_of(self.reorder))

	def test_a_telegram_that_does_not_answer_is_waited_for_not_given_up_on(self):
		self.telegram.fail.append(
			("getUpdates", 502, {"ok": False, "error_code": 502, "description": f"Bad Gateway {TOKEN}"})
		)
		with self.assertLogs(frappe.logger("ai_munimji").name, level="WARNING") as logged:
			out = self.run_the_loop([True, True, True, False, False])
		self.assertEqual(out["ran"], True)
		self.assertNotIn(TOKEN, "\n".join(logged.output))
		self.assertEqual(len(self.telegram.of("getUpdates")), 2, "it asked again")

	def test_it_stops_when_telegram_is_switched_off_or_set_to_webhook_and_does_not_start_again(self):
		out = self.run_the_loop([False])
		self.assertEqual(out["ran"], False)
		self.assertEqual(self.telegram.of("getUpdates"), [])
		self.assertEqual(
			[c for c in self.enqueued.call_args_list if c.args and c.args[0] == telegram_jobs.POLL], []
		)

	def test_it_queues_its_successor_while_it_is_still_wanted(self):
		self.run_the_loop([True, False, True])
		queued = [c for c in self.enqueued.call_args_list if c.args and c.args[0] == telegram_jobs.POLL]
		self.assertEqual(len(queued), 1)
		self.assertEqual(queued[0].kwargs["queue"], "long")

	def test_two_loops_do_not_run_at_once(self):
		frappe.set_user("Administrator")
		locks.lease.return_value = False
		with mock.patch.object(telegram_jobs, "wanted", return_value=True):
			out = telegram_jobs.poll()
		self.assertEqual(out, {"ran": False, "why": "another poller is running"})
		self.assertEqual(self.telegram.calls, [])

	def test_the_housekeeping_starts_a_loop_only_when_one_is_wanted_and_none_runs(self):
		frappe.set_user("Administrator")
		with mock.patch.object(locks, "held", return_value=True):
			self.assertEqual(telegram_jobs.ensure_poller(), "running")
		with mock.patch.object(locks, "held", return_value=False):
			self.assertEqual(telegram_jobs.ensure_poller(), "queued")
			self.switch_telegram(True, mode="Webhook")
			self.assertEqual(telegram_jobs.ensure_poller(), "not wanted")
			self.switch_telegram(False)
			self.assertEqual(telegram_jobs.ensure_poller(), "not wanted")
