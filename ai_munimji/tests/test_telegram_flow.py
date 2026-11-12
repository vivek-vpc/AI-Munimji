"""A request goes to Telegram, a person answers there, and what the Desk and the chat say agree (AI Munimji Telegram, A1 and A2).

On a fake stock and a fake Telegram, with the real engine, the real stores and the real permissions: the stock check never calls Telegram while it holds rows locked; a job sends what it made;
a button press is the connected person's own answer, with their rights; a duplicate is ignored; the Desk and the chat tidy each other; a number typed in reply changes a quantity;
reminders go to the people who were sent the request; and a Telegram that is down never stops a person answering in the Desk.
"""

import time
from datetime import timedelta
from unittest import mock

import frappe
import requests
from ai_munimji_engine.core.common import iso, utcnow

from ai_munimji import jobs
from ai_munimji.stores import frappe_core_stores, locks
from ai_munimji.telegram import config, inbound, links, outbox, transport
from ai_munimji.telegram import jobs as telegram_jobs
from ai_munimji.tests.helpers import APPROVER_ROLES, make_user
from ai_munimji.tests.telegram_kit import TOKEN, TelegramCase, message, press
from ai_munimji.tests.test_vendor_comparison import APPROVED_REORDER, FakeBuyer


class WatchedBuyer(FakeBuyer):
	"""A fake stock that remembers who was signed in to Frappe when a draft order was asked for: ERPNext makes the order in that person's name and with that person's rights."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.made_by = []

	def create_purchase_order(self, draft, acting=None):
		self.made_by.append(frappe.session.user)
		return super().create_purchase_order(draft, acting)


class FlowOnTelegram(TelegramCase):
	"""Alice and Bob are connected, a reorder is waiting, and it has been sent to both."""

	def make_erp(self):
		return WatchedBuyer(count=3, low=(0,))

	def setUp(self):
		super().setUp()
		self.connect("alice")
		self.connect("bob")
		self.reorder = self.raise_a_reorder()
		self.deliver()
		self.telegram.calls.clear()

	def deliveries(self, approval_id):
		return frappe_core_stores(system=True).approvals.deliveries(approval_id)

	def message_of(self, approval_id, who):
		"""The Telegram message id of the request as `who` was sent it."""
		return next(d["external_id"] for d in self.deliveries(approval_id) if d["address"] == self.CHAT[who])

	def make_the_purchase_request(self):
		"""Approve the reorder in the Desk and run the vendor comparison; returns the purchase request's id."""
		self.desk_answer(self.reorder, "approve", "alice")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(request,) = self.pending("procurement.po")
		self.deliver()
		self.telegram.calls.clear()
		return request["id"]


class TestSendingRequests(TelegramCase):
	def make_erp(self):
		return FakeBuyer(count=3, low=(0,))

	def test_a_stock_check_never_calls_telegram_and_asks_for_a_delivery_once_it_is_committed(self):
		self.connect("alice")
		self.telegram.calls.clear()
		self.raise_a_reorder()
		self.assertEqual(self.telegram.calls, [], "no call to Telegram while the check holds rows locked")
		asked = [c for c in self.enqueued.call_args_list if c.args and c.args[0] == outbox.JOB]
		self.assertTrue(asked)
		self.assertTrue(
			all(c.kwargs["enqueue_after_commit"] and c.kwargs["deduplicate"] for c in asked), asked
		)

	def test_the_delivery_job_sends_each_waiting_request_once_to_each_connected_approver(self):
		self.connect("alice")
		self.connect("bob")
		request = self.raise_a_reorder()
		report = self.deliver()
		self.assertEqual(report, {"ran": True, "sent": 2})
		for who in ("alice", "bob"):
			[sent] = self.telegram.request_messages(self.CHAT[who])
			self.assertEqual(
				[action for _label, action in self.telegram.buttons(sent)][:3],
				["approve", "snooze", "dismiss"],
			)
			self.assertIn("Start reorder", [label for label, _action in self.telegram.buttons(sent)])
		rows = frappe_core_stores(system=True).approvals.deliveries(request)
		self.assertEqual(sorted(r["address"] for r in rows), ["1001", "1002"])
		self.assertTrue(all(r["status"] == "sent" and r["external_id"] for r in rows))
		self.assertEqual(self.deliver()["sent"], 0, "nothing is sent twice")

	def test_nobody_who_may_not_answer_is_sent_anything(self):
		self.connect("alice")
		frappe.db.set_value("Munimji Telegram Link", self.alice, "enabled", 0)
		self.telegram.calls.clear()
		self.raise_a_reorder()
		self.assertEqual(self.deliver()["sent"], 0)
		self.assertEqual(self.telegram.sent("1001"), [])

	def test_a_person_who_connects_later_is_sent_the_requests_made_from_then_on_only(self):
		self.raise_a_reorder()
		time.sleep(1.1)  # a request and a link are told apart by the second they were made in
		self.connect("alice")
		time.sleep(1.1)
		self.assertEqual(self.deliver()["sent"], 0, "the request that was waiting stays in the Desk")
		self.erp.low.add("FS-001")
		self.assertEqual(self.scheduled_check()["alerts"], 1)
		self.assertEqual(self.deliver()["sent"], 1)
		[sent] = self.telegram.request_messages("1001")
		self.assertIn("FS-001", sent["text"])

	def test_a_failed_send_is_tried_again_by_the_housekeeping_and_given_up_after_five(self):
		self.connect("alice")
		self.raise_a_reorder()
		self.telegram.fail.append(
			("sendMessage", 502, {"ok": False, "error_code": 502, "description": "Bad Gateway"})
		)
		self.deliver()
		request_id = self.pending()[0]["id"]
		[row] = self.deliveries(request_id)
		self.assertEqual(row["status"], "failed")
		self.assertEqual(
			self.deliver()["sent"], 0, "a failed send is the housekeeping's to retry, not a new send"
		)
		report = telegram_jobs.housekeeping()
		self.assertEqual(report["retried"], 1)
		self.assertEqual(
			len(self.telegram.request_messages("1001")), 2, "the attempt that failed and the one that worked"
		)
		[row] = self.deliveries(request_id)
		self.assertEqual((row["status"], row["attempts"]), ("sent", 2))

	def test_a_send_that_keeps_failing_is_given_up(self):
		self.connect("alice")
		self.raise_a_reorder()
		for _ in range(6):
			self.telegram.fail.append(
				("sendMessage", 502, {"ok": False, "error_code": 502, "description": "Bad Gateway"})
			)
		self.deliver()
		for _ in range(5):
			telegram_jobs.housekeeping()
		[row] = self.deliveries(self.pending()[0]["id"])
		self.assertEqual((row["status"], row["attempts"]), ("given_up", 5))

	def deliveries(self, approval_id):
		return frappe_core_stores(system=True).approvals.deliveries(approval_id)


class TestReminders(FlowOnTelegram):
	def reminders_at(self, hours_later: float):
		page = frappe.get_doc("AI Munimji Settings")
		page.reminder_after_hours, page.max_reminders = 1, 2
		page.save()
		frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")
		later = utcnow() + timedelta(hours=hours_later)
		frappe.set_user("Administrator")
		services = jobs.system_services(clock=lambda: later, telegram=True)
		return outbox.remind(services)

	def test_nobody_is_reminded_before_the_time_is_up(self):
		self.assertEqual(self.reminders_at(0.5), [])
		self.assertEqual(self.telegram.calls, [])

	def test_the_people_who_were_sent_the_request_are_reminded_up_to_the_limit(self):
		self.assertEqual(self.reminders_at(2), [self.reorder])
		for who in ("alice", "bob"):
			self.assertTrue(self.telegram.texts(self.CHAT[who])[-1].startswith("Reminder: "), who)
		self.assertEqual(self.reminders_at(2), [], "not again at once: the count and the time are kept")
		self.assertEqual(self.reminders_at(4), [self.reorder])
		self.assertEqual(self.reminders_at(8), [], "the limit is two")

	def test_a_person_who_connected_after_the_request_has_no_message_to_scroll_up_to(self):
		self.connect("manager")
		self.assertEqual(self.reminders_at(2), [self.reorder])
		self.assertEqual(
			self.telegram.sent(self.CHAT["manager"])[-1]["text"],
			"Connected. Requests that need your answer will arrive here, with buttons.",
		)

	def test_a_person_whose_send_failed_has_no_message_to_scroll_up_to_either(self):
		[bobs] = [d for d in self.deliveries(self.reorder) if d["address"] == self.CHAT["bob"]]
		frappe_core_stores(system=True).approvals.update_delivery(
			bobs["id"], "failed", None, "Bad Gateway", 1, iso(utcnow())
		)
		bob_has = len(self.telegram.texts(self.CHAT["bob"]))
		self.assertEqual(self.reminders_at(2), [self.reorder])
		self.assertTrue(self.telegram.texts(self.CHAT["alice"])[-1].startswith("Reminder: "))
		self.assertEqual(
			len(self.telegram.texts(self.CHAT["bob"])),
			bob_has,
			"nothing to remind him of: he was not sent it",
		)

	def test_the_housekeeping_does_nothing_while_telegram_is_off(self):
		self.switch_telegram(False)
		self.assertEqual(telegram_jobs.housekeeping(), {"ran": False, "why": "Telegram is off"})
		self.assertEqual(telegram_jobs.deliver_new()["ran"], False)


class TestAnsweringFromTelegram(FlowOnTelegram):
	def test_a_press_is_the_connected_persons_own_decision(self):
		self.assertEqual(self.press_as("alice", self.reorder, "approve"), "handled")
		decision = self.decision_of(self.reorder)
		self.assertEqual(
			(decision["action"], decision["actor_id"], decision["channel"]),
			("approve", self.alice, "telegram"),
		)
		self.assertEqual(len(self.telegram.toasts()), 1)
		self.assertTrue(
			self.telegram.toasts()[0].startswith(f"Recorded: Start reorder (by {self.alice} via telegram)."),
			self.telegram.toasts(),
		)
		(work_order,) = self.waiting_work_orders()
		queued = self.queued()
		self.assertEqual(len(queued), 1, "approving a reorder queues the vendor comparison, as in the Desk")
		self.assertEqual(queued[0].kwargs["work_order_id"], work_order["id"])

	def test_the_chat_is_told_what_happens_next_in_the_same_words_as_the_desk(self):
		self.press_as("alice", self.reorder, "approve")
		self.assertEqual(self.telegram.texts("1001")[-1], APPROVED_REORDER)

	def test_both_chats_are_tidied_when_one_person_answers(self):
		self.press_as("alice", self.reorder, "approve")
		edited = self.telegram.of("editMessageReplyMarkup")
		self.assertEqual(sorted(str(e["chat_id"]) for e in edited), ["1001", "1002"])
		self.assertTrue(all(e["reply_markup"] == {"inline_keyboard": []} for e in edited))
		for who in ("alice", "bob"):
			replies = [
				p
				for p in self.telegram.sent(self.CHAT[who])
				if p.get("reply_to_message_id") == int(self.message_of(self.reorder, who))
			]
			self.assertTrue(replies and replies[0]["text"].startswith("Recorded: Start reorder"), who)

	def test_the_second_press_is_refused_and_says_who_answered_first(self):
		self.press_as("alice", self.reorder, "approve")
		self.telegram.calls.clear()
		self.press_as("bob", self.reorder, "dismiss")
		self.assertTrue(self.telegram.toasts()[-1].startswith("Already answered: Start reorder"))
		self.assertEqual(self.decision_of(self.reorder)["actor_id"], self.alice)

	def test_the_same_update_delivered_twice_decides_once(self):
		payload = press("1001", self.reorder, "approve", update_id=4242)
		self.assertEqual(self.update(payload), "handled")
		self.assertEqual(self.update(payload), "duplicate")
		self.assertEqual(len(self.queued()), 1)

	def test_a_stranger_pressing_a_button_changes_nothing(self):
		self.assertEqual(self.update(press("9999", self.reorder, "approve")), "stranger")
		self.assertEqual(self.telegram.toasts(), ["You are not registered to answer these requests."])
		self.assertIsNone(self.decision_of(self.reorder))

	def test_a_user_who_is_disabled_is_a_stranger_even_in_a_chat_that_was_theirs(self):
		frappe.db.set_value("User", self.alice, "enabled", 0)
		self.assertEqual(self.press_as("alice", self.reorder, "approve"), "stranger")
		self.assertIsNone(self.decision_of(self.reorder))

	def test_a_user_who_lost_the_approver_role_is_a_stranger(self):
		carol = make_user(
			"tg.dave@example.com", APPROVER_ROLES
		)  # her own user: Frappe keeps a user's roles in a cache that a rollback does not undo
		frappe.set_user("Administrator")
		code = links.issue_code(carol)
		self.assertEqual(self.update(message("3002", f"/start {code}")), "linked")
		frappe.get_doc("User", carol).remove_roles("Munimji Approver")
		frappe.clear_cache(user=carol)
		self.assertEqual(self.update(press("3002", self.reorder, "approve")), "stranger")
		self.assertIsNone(self.decision_of(self.reorder))

	def test_details_are_sent_and_the_request_stays_open(self):
		self.press_as("alice", self.reorder, "details")
		self.assertEqual(self.telegram.toasts(), ["Details sent"])
		self.assertIsNone(self.decision_of(self.reorder))
		self.assertTrue(self.telegram.texts("1001"))

	def test_free_text_gets_one_sentence_and_changes_nothing(self):
		self.say_as("alice", "approve everything please")
		self.assertTrue(self.telegram.texts("1001")[-1].startswith("I take answers to requests here"))
		self.assertIsNone(self.decision_of(self.reorder))

	def test_a_stranger_who_writes_is_told_only_their_own_chat_id_and_only_once_in_a_while(self):
		for text in ("/start", "hello", "/id"):
			self.update(message("7777", text))
		[reply] = self.telegram.texts("7777")
		self.assertIn("7777", reply)
		self.assertNotIn("1001", reply)
		self.assertIn("person who runs AI Munimji", reply)

	def test_a_registered_person_who_writes_start_is_told_how_it_works(self):
		self.say_as("alice", "/start")
		self.assertTrue(self.telegram.texts("1001")[-1].startswith("You are set up on AI Munimji."))

	def test_groups_and_bots_are_ignored(self):
		group = message("1001", "approve")
		group["message"]["chat"]["type"] = "group"
		bot = message("1001", "approve")
		bot["message"]["from"]["is_bot"] = True
		self.assertEqual((self.update(group), self.update(bot)), ("ignored", "ignored"))
		self.assertEqual(self.telegram.calls, [])


class TestTheWholeWayByButtons(FlowOnTelegram):
	def test_from_the_reorder_to_a_draft_order_without_opening_the_desk(self):
		self.press_as("alice", self.reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(purchase,) = self.pending("procurement.po")
		self.deliver()
		for who in ("alice", "bob"):
			[message_] = [
				p
				for p in self.telegram.request_messages(self.CHAT[who])
				if "Create order" in [label for label, _a in self.telegram.buttons(p)]
			]
			self.assertIn("FS-000", message_["text"])
		self.telegram.calls.clear()
		self.press_as("bob", purchase["id"], "approve")
		self.assertEqual(len(self.erp.made), 1, "a draft order was asked for")
		self.assertEqual(self.erp.made_by, [self.bob], "made as Bob, with Bob's rights, not as the system")
		self.assertEqual(self.decision_of(purchase["id"])["actor_id"], self.bob)
		self.assertEqual(
			self.telegram.texts("1002")[-1],
			"Draft Purchase Order PUR-ORD-FAKE-0001 made. Review and submit it in ERPNext.",
		)
		self.assertEqual(
			len(self.telegram.of("editMessageReplyMarkup")),
			2,
			"both chats lose the buttons of the order request",
		)

	def test_a_second_press_on_the_order_makes_no_second_order(self):
		purchase = self.make_the_purchase_request()
		self.press_as("alice", purchase, "approve")
		self.press_as("bob", purchase, "approve")
		self.assertEqual(len(self.erp.made), 1)

	def test_change_quantity_asks_and_the_typed_number_makes_a_revised_request_that_arrives_last(self):
		purchase = self.make_the_purchase_request()
		self.press_as("alice", purchase, "change_qty")
		self.assertIn("Type your answer", self.telegram.toasts()[-1])
		self.assertTrue(self.telegram.texts("1001")[-1])
		self.telegram.calls.clear()
		self.say_as("alice", "250")
		self.assertEqual(
			self.pending("procurement.po")[0]["id"] != purchase, True, "the request was replaced"
		)
		texts = self.telegram.texts("1001")
		self.assertTrue(any(t.startswith("Done") for t in texts), texts)
		self.assertTrue(self.telegram.request_messages("1001"), "the revised request, with its buttons")
		order = [n for n, p, _t in self.telegram.calls if n == "sendMessage" and str(p["chat_id"]) == "1001"]
		self.assertGreaterEqual(len(order), 2)
		last = [p for n, p, _t in self.telegram.calls if n == "sendMessage" and str(p["chat_id"]) == "1001"][
			-1
		]
		self.assertTrue(last.get("reply_markup"), "the revised request is the last message in the chat")
		(revised,) = self.pending("procurement.po")
		self.assertEqual(float(frappe.db.get_value("Munimji Approval Request", revised["id"], "qty")), 250.0)

	def test_a_number_in_reply_to_the_order_message_changes_its_quantity(self):
		purchase = self.make_the_purchase_request()
		reply_to = self.message_of(purchase, "bob")
		self.update(message("1002", "300", reply_to=reply_to))
		(revised,) = self.pending("procurement.po")
		self.assertNotEqual(revised["id"], purchase)
		self.assertEqual(float(frappe.db.get_value("Munimji Approval Request", revised["id"], "qty")), 300.0)

	def test_an_answer_that_comes_too_late_is_not_taken(self):
		purchase = self.make_the_purchase_request()
		self.press_as("alice", purchase, "change_qty")
		later = time.time() + 3600
		with mock.patch.object(inbound.time, "time", lambda: later):
			self.say_as("alice", "500")
		self.assertEqual([r["id"] for r in self.pending("procurement.po")], [purchase])


class TestTheDeskAndTelegramTogether(FlowOnTelegram):
	def test_an_answer_in_the_desk_tidies_the_chats_with_short_calls(self):
		self.desk_answer(self.reorder, "dismiss", "alice")
		edited = self.telegram.of("editMessageReplyMarkup")
		self.assertEqual(sorted(str(e["chat_id"]) for e in edited), ["1001", "1002"])
		self.assertTrue(
			all(timeout <= 5 for name, _p, timeout in self.telegram.calls), "a person is waiting for the page"
		)
		replies = [p for p in self.telegram.sent("1002") if p.get("reply_to_message_id")]
		self.assertIn(f"by {self.alice} via desk", replies[0]["text"])

	def test_a_telegram_that_is_down_never_stops_an_answer_in_the_desk(self):
		def down(url, json=None, timeout=15):
			raise ConnectionError("ReadTimeout")

		self.telegram.post = down
		said = self.desk_answer(self.reorder, "dismiss", "alice")
		self.assertTrue(said["ok"], said)
		self.assertEqual(self.decision_of(self.reorder)["actor_id"], self.alice)

	def test_after_three_failures_telegram_is_left_alone_for_a_minute_and_the_error_has_no_token(self):
		calls = []

		def down(session, url, **kwargs):
			calls.append(url)
			raise requests.ConnectionError(
				f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: /bot{TOKEN}/getMe"
			)

		http = self.real_http()
		url = f"https://api.telegram.org/bot{TOKEN}/getMe"
		with mock.patch.object(requests.Session, "post", down):
			for _ in range(3):
				with self.assertRaises(ConnectionError) as raised:
					http.post(url, json={})
				self.assertNotIn(TOKEN.split(":")[1], str(raised.exception))
			self.assertTrue(transport.breaker_open())
			with self.assertRaises(ConnectionError) as raised:
				http.post(url, json={})
			self.assertIn("not tried again for a minute", str(raised.exception))
		self.assertEqual(len(calls), 3, "the fourth call was not even made")
		transport.reset_breaker()
		self.assertFalse(transport.breaker_open())

	def test_the_revised_request_made_in_the_desk_is_sent_to_the_chats(self):
		purchase = self.make_the_purchase_request()
		self.desk_answer(purchase, "change_qty", "alice", qty=120)
		for who in ("alice", "bob"):
			self.assertTrue(self.telegram.request_messages(self.CHAT[who]), who)
		(revised,) = self.pending("procurement.po")
		self.assertNotEqual(revised["id"], purchase)

	def test_a_request_answered_in_the_desk_is_not_sent_afterwards(self):
		self.desk_answer(self.reorder, "dismiss", "alice")
		self.telegram.calls.clear()
		self.assertEqual(self.deliver()["sent"], 0)
		self.assertEqual(self.telegram.calls, [])


class TestStillOffOnTheOtherSideOfTheSwitch(TelegramCase):
	def test_with_telegram_switched_off_a_desk_answer_uses_no_channel_at_all(self):
		self.connect("alice")
		request = self.raise_a_reorder()
		self.deliver()
		self.switch_telegram(False)
		self.telegram.calls.clear()
		said = self.desk_answer(request, "dismiss", "alice")
		self.assertTrue(said["ok"], said)
		self.assertEqual(self.telegram.calls, [], "switched off means nothing leaves")
		self.assertFalse(config.on())
		self.assertEqual(inbound.handle_update(message("1001", "hello")), "off")


class TestOneDeliveryAtATime(TelegramCase):
	"""A request is sent to a person when no message of it has been recorded for them, so two runs at once would both send it. The queued delivery and the housekeeping can overlap."""

	def make_erp(self):
		return FakeBuyer(count=3, low=(0,))

	def test_a_delivery_that_finds_another_one_running_leaves_what_is_left_to_the_next_run(self):
		self.connect("alice")
		self.raise_a_reorder()
		self.telegram.calls.clear()
		locks.lease.side_effect = [False]
		self.assertEqual(
			telegram_jobs.deliver_new(), {"ran": False, "why": "another delivery is running", "sent": 0}
		)
		self.assertEqual(self.telegram.calls, [])
		locks.lease.side_effect = None
		self.assertEqual(telegram_jobs.deliver_new()["sent"], 1, "the next run sends it")

	def test_the_housekeeping_does_not_run_beside_a_delivery_either(self):
		self.connect("alice")
		locks.lease.side_effect = [False]
		self.assertEqual(telegram_jobs.housekeeping(), {"ran": False, "why": "another delivery is running"})

	def test_the_lease_is_taken_for_the_delivery_and_given_back_afterwards_even_if_it_fails(self):
		self.connect("alice")
		holders = []
		locks.lease.side_effect = (
			lambda name, holder, minutes: holders.append((name, holder, minutes)) or True
		)
		with (
			mock.patch.object(outbox, "deliver_pending", side_effect=RuntimeError("boom")),
			self.assertRaises(RuntimeError),
		):
			telegram_jobs.deliver_new()
		[(name, holder, minutes)] = holders
		self.assertEqual((name, minutes), (telegram_jobs.OUTBOX_LEASE, telegram_jobs.OUTBOX_LEASE_MINUTES))
		locks.release.assert_called_once_with(telegram_jobs.OUTBOX_LEASE, holder)

	def test_two_runs_that_do_overlap_in_time_send_a_request_once(self):
		"""The overlap itself: while the first run is sending, a second one is started. With the lease the second leaves; without it both would send."""
		self.connect("alice")
		self.raise_a_reorder()
		self.telegram.calls.clear()
		inner = []

		def while_the_first_is_sending(services):
			locks.lease.side_effect = [False]  # the lease is taken: the second run is refused
			inner.append(telegram_jobs.deliver_new())
			locks.lease.side_effect = None
			return real(services)

		real = outbox.deliver_pending
		with mock.patch.object(outbox, "deliver_pending", while_the_first_is_sending):
			first = telegram_jobs.deliver_new()
		self.assertEqual((first["sent"], inner[0]["ran"]), (1, False))
		self.assertEqual(len(self.telegram.request_messages("1001")), 1)
