"""Telegram is off until it is switched on, and a chat is a person only after the person proved it (AI Munimji Telegram, A1).

What is shown: the switch and the token on the Settings page; the Connect Telegram link and its one-time code; what the bot tells a person who connects, a stranger, and a person who may not
answer; who sees whose link; and that the bot token is nowhere a person can read it.
"""

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji import wiring
from ai_munimji.telegram import api, config, links, outbox, webhook
from ai_munimji.tests.helpers import APPROVER_ROLES, make_user
from ai_munimji.tests.telegram_kit import BOT, TOKEN, TelegramCase, message

LINK = "Munimji Telegram Link"


class TestTelegramIsOffUntilSwitchedOn(TelegramCase):
	def setUp(self):
		super().setUp()
		self.switch_telegram(False)

	def test_nothing_is_sent_or_accepted_while_it_is_off(self):
		self.assertFalse(config.on())
		self.assertIsNone(wiring.telegram_router())
		self.assertEqual(self.update(message("1001", "/start")), "off")
		with self.assertRaises(frappe.PermissionError):
			webhook.verify_secret()
		self.assertEqual(self.telegram.calls, [])

	def test_a_stock_check_makes_its_requests_and_never_calls_telegram(self):
		request = self.raise_a_reorder()
		self.assertTrue(request)
		self.assertEqual(self.telegram.calls, [])
		outbox.nudge()
		self.assertFalse(
			[c for c in self.enqueued.call_args_list if c.args and c.args[0] == outbox.JOB],
			"nothing is asked of the queue",
		)

	def test_the_settings_page_holds_no_telegram_by_default(self):
		fresh = frappe.new_doc("AI Munimji Settings")
		self.assertEqual(int(fresh.telegram_enabled or 0), 0)
		self.assertEqual(fresh.telegram_mode, "Webhook")

	def test_switching_it_on_asks_for_the_token(self):
		frappe.db.delete(
			"__Auth", {"doctype": "AI Munimji Settings", "fieldname": "telegram_bot_token"}
		)  # no token has been given on this site
		page = frappe.get_doc("AI Munimji Settings")
		page.telegram_enabled = 1
		page.telegram_bot_token = ""
		with self.assertRaises(frappe.ValidationError) as raised:
			page.save()
		self.assertIn("Bot token", str(raised.exception))
		self.assertIn("BotFather", str(raised.exception))

	def test_switching_it_on_with_a_token_makes_the_webhook_secret_and_keeps_both_encrypted(self):
		self.switch_telegram(True)
		self.assertTrue(config.on() and config.enabled())
		self.assertEqual(config.token(), TOKEN)
		secret = config.webhook_secret()
		self.assertRegex(secret, r"^[A-Za-z0-9_-]{32}$", "what Telegram accepts as a secret")
		stored = frappe.db.sql(
			"select `password` from `__Auth` where doctype=%s and name=%s and fieldname=%s",
			("AI Munimji Settings", "AI Munimji Settings", "telegram_bot_token"),
		)
		self.assertTrue(stored and TOKEN not in stored[0][0], "the token is kept encrypted")
		page = frappe.get_doc("AI Munimji Settings")
		self.assertNotIn(TOKEN, str(page.as_dict()))
		self.assertNotIn(secret, str(page.as_dict()))

	def test_saving_the_page_again_keeps_the_secret_and_the_token(self):
		self.switch_telegram(True)
		secret = config.webhook_secret()
		page = frappe.get_doc("AI Munimji Settings")
		page.min_qty = 11
		page.save()
		frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")
		self.assertEqual((config.token(), config.webhook_secret()), (TOKEN, secret))

	def test_the_housekeeping_job_runs_only_while_telegram_is_on(self):
		from ai_munimji import schedule

		name = frappe.db.get_value("Scheduled Job Type", {"method": schedule.TELEGRAM}, "name")
		self.assertTrue(name)
		self.assertEqual(frappe.db.get_value("Scheduled Job Type", name, "stopped"), 1)
		self.switch_telegram(True)
		self.assertEqual(frappe.db.get_value("Scheduled Job Type", name, "stopped"), 0)
		self.switch_telegram(False)
		self.assertEqual(frappe.db.get_value("Scheduled Job Type", name, "stopped"), 1)


class TestTheLinkAPerson(TelegramCase):
	def test_only_the_people_who_answer_requests_get_a_link(self):
		for user in (self.alice, self.tg_manager):
			frappe.set_user(user)
			out = api.connect()
			self.assertTrue(out["ok"], out)
			self.assertRegex(out["link"], rf"^https://t\.me/{BOT}\?start=[A-Za-z0-9_-]{{8,64}}$")
			self.assertEqual(out["bot"], f"@{BOT}")
		frappe.set_user(self.tg_viewer)
		with self.assertRaises(frappe.PermissionError):
			api.connect()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.connect()

	def test_it_says_so_when_telegram_is_off_or_the_bot_is_not_connected(self):
		frappe.set_user(self.alice)
		self.switch_telegram(True, username="")
		frappe.set_user(self.alice)
		self.assertIn("not connected yet", api.connect()["message"])
		self.switch_telegram(False)
		frappe.set_user(self.alice)
		self.assertIn("not switched on", api.connect()["message"])

	def test_a_user_who_cannot_answer_requests_is_told_so_before_a_code_is_made(self):
		frappe.set_user("Administrator")
		out = api.connect()
		self.assertFalse(out["ok"])
		self.assertIn("cannot answer requests", out["message"])

	def test_the_chat_that_presses_start_with_the_code_becomes_the_person(self):
		chat = self.connect("alice")
		self.assertEqual(links.user_for_chat(chat), self.alice)
		self.assertEqual(frappe.db.get_value(LINK, self.alice, "chat_id"), chat)
		self.assertEqual(
			frappe.db.get_value(LINK, self.alice, "owner"),
			self.alice,
			"the person owns their link, not the bot",
		)
		self.assertEqual(
			self.telegram.texts(chat)[-1],
			"Connected. Requests that need your answer will arrive here, with buttons.",
		)

	def test_a_code_works_once(self):
		frappe.set_user("Administrator")
		code = links.issue_code(self.alice)
		self.assertEqual(self.update(message("1001", f"/start {code}")), "linked")
		self.assertEqual(self.update(message("1005", f"/start {code}")), "refused_link")
		self.assertIn("expired or was already used", self.telegram.texts("1005")[-1])
		self.assertIsNone(links.user_for_chat("1005"))

	def test_a_made_up_code_connects_nobody(self):
		self.assertEqual(self.update(message("1005", "/start abcdefghijkl")), "refused_link")
		self.assertIsNone(links.user_for_chat("1005"))

	def test_a_new_code_cancels_the_one_before(self):
		frappe.set_user("Administrator")
		first, second = links.issue_code(self.alice), links.issue_code(self.alice)
		self.assertEqual(self.update(message("1001", f"/start {first}")), "refused_link")
		self.assertEqual(self.update(message("1001", f"/start {second}")), "linked")

	def test_a_code_is_kept_as_a_hash_and_is_not_a_chat_id(self):
		frappe.set_user("Administrator")
		code = links.issue_code(self.alice)
		keys = frappe.cache.get_keys("ai_munimji:telegram:code:*")
		self.assertTrue(
			keys and all(code not in (k.decode() if isinstance(k, bytes) else k) for k in keys),
			"the cache holds the hash, not the code",
		)

	def test_a_user_who_may_not_answer_requests_is_not_connected_even_with_a_valid_code(self):
		frappe.set_user("Administrator")
		code = links.issue_code(self.tg_viewer)
		self.assertEqual(self.update(message("1003", f"/start {code}")), "refused_link")
		self.assertIn("cannot answer requests", self.telegram.texts("1003")[-1])
		self.assertIsNone(frappe.db.exists(LINK, self.tg_viewer))

	def test_a_chat_cannot_be_two_people(self):
		self.connect("alice")
		frappe.set_user("Administrator")
		code = links.issue_code(self.bob)
		self.assertEqual(self.update(message(self.CHAT["alice"], f"/start {code}")), "refused_link")
		self.assertIn("already connected to another", self.telegram.texts(self.CHAT["alice"])[-1])
		self.assertEqual(links.user_for_chat(self.CHAT["alice"]), self.alice)

	def test_a_person_who_connects_another_chat_moves_there_and_the_old_chat_is_told(self):
		self.connect("alice")
		frappe.set_user("Administrator")
		code = links.issue_code(self.alice)
		self.assertEqual(self.update(message("2001", f"/start {code}")), "linked")
		self.assertEqual(links.chat_of(self.alice), "2001")
		self.assertIsNone(links.user_for_chat(self.CHAT["alice"]))
		self.assertIn("no longer gets requests", self.telegram.texts(self.CHAT["alice"])[-1])

	def test_the_same_update_delivered_again_connects_once_and_says_nothing_more(self):
		frappe.set_user("Administrator")
		code = links.issue_code(self.alice)
		payload = message("1001", f"/start {code}", update_id=777)
		self.assertEqual(self.update(payload), "linked")
		told = len(self.telegram.sent("1001"))
		self.assertEqual(self.update(payload), "duplicate")
		self.assertEqual(len(self.telegram.sent("1001")), told)

	def test_a_person_can_disconnect_and_is_then_a_stranger(self):
		chat = self.connect("alice")
		frappe.set_user(self.alice)
		self.assertTrue(api.connection()["connected"])
		self.assertTrue(api.disconnect()["ok"])
		self.assertFalse(api.connection()["connected"])
		self.assertIsNone(links.user_for_chat(chat))
		self.assertIn("was not connected", api.disconnect()["message"])

	def test_switching_requests_off_keeps_the_link_and_stops_the_messages(self):
		chat = self.connect("alice")
		frappe.db.set_value(LINK, self.alice, "enabled", 0)
		self.assertIsNone(links.user_for_chat(chat))
		self.assertEqual(links.recipients(), [])

	def test_a_user_who_is_disabled_or_loses_the_role_is_no_longer_the_chat(self):
		carol = make_user(
			"tg.carol@example.com", APPROVER_ROLES
		)  # her own user: Frappe keeps a user's roles in a cache that a rollback does not undo
		frappe.set_user("Administrator")
		code = links.issue_code(carol)
		self.assertEqual(self.update(message("3001", f"/start {code}")), "linked")
		frappe.db.set_value("User", carol, "enabled", 0)
		self.assertIsNone(links.user_for_chat("3001"))
		frappe.db.set_value("User", carol, "enabled", 1)
		self.assertEqual(links.user_for_chat("3001"), carol)
		frappe.get_doc("User", carol).remove_roles("Munimji Approver")
		frappe.clear_cache(user=carol)
		self.assertIsNone(links.user_for_chat("3001"))

	def test_deleting_a_user_deletes_their_link(self):
		self.connect("bob")
		frappe.set_user("Administrator")
		frappe.delete_doc("User", self.bob, force=True, ignore_permissions=True)
		self.assertIsNone(frappe.db.exists(LINK, self.bob))


class TestWhoSeesWhoseLink(TelegramCase):
	def setUp(self):
		super().setUp()
		self.connect("alice")
		self.connect("bob")

	def listed(self, user):
		frappe.set_user(user)
		return sorted(frappe.get_list(LINK, pluck="name"))

	def test_a_person_sees_their_own_link_and_a_manager_sees_all(self):
		self.assertEqual(self.listed(self.alice), [self.alice])
		self.assertEqual(self.listed(self.bob), [self.bob])
		self.assertEqual(self.listed(self.tg_manager), sorted([self.alice, self.bob]))
		self.assertEqual(self.listed("Administrator"), sorted([self.alice, self.bob]))

	def test_a_person_cannot_open_change_or_delete_another_persons_link(self):
		frappe.set_user(self.alice)
		for right in ("read", "write", "delete"):
			self.assertFalse(frappe.has_permission(LINK, right, doc=self.bob), right)
			self.assertTrue(frappe.has_permission(LINK, right, doc=self.alice), right)

	def test_a_viewer_and_a_stranger_see_none(self):
		for user in (self.tg_viewer, "Guest"):
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission(LINK, "read"), user)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_list(LINK)

	def test_nobody_creates_a_link_by_hand(self):
		for user in (self.alice, self.tg_manager):
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission(LINK, "create"), user)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc({"doctype": LINK, "user": user, "chat_id": "999"}).insert()

	def test_a_manager_can_disconnect_someone_and_that_person_is_then_a_stranger(self):
		frappe.set_user(self.tg_manager)
		frappe.delete_doc(LINK, self.bob)
		self.assertIsNone(links.user_for_chat(self.CHAT["bob"]))


class TestTheTokenIsNowhereAPersonCanRead(TelegramCase):
	def test_the_status_and_the_buttons_never_carry_the_token_or_the_secret(self):
		frappe.set_user(self.tg_manager)
		everything = str(api.status()) + str(api.connect_bot()) + str(api.send_test())
		self.assertNotIn(TOKEN, everything)
		self.assertNotIn(TOKEN.split(":")[1], everything)
		self.assertNotIn(config.webhook_secret(), everything)

	def test_the_token_and_the_secret_are_neither_in_the_table_nor_in_the_version_log_nor_in_an_error_log(
		self,
	):
		secret = config.webhook_secret()
		page = frappe.get_doc("AI Munimji Settings")
		page.min_qty = (
			12  # a save after the token was given, which writes a Version (the page tracks changes)
		)
		page.save()
		for text in (TOKEN, TOKEN.split(":")[1], secret):
			for table, column in (
				("tabSingles", "value"),
				("tabVersion", "data"),
				("`tabError Log`", "error"),
				("`tabActivity Log`", "content"),
				("`tabComment`", "content"),
			):
				table = table if table.startswith("`") else f"`{table}`"
				found = frappe.db.sql(f"select count(*) from {table} where {column} like %s", (f"%{text}%",))[
					0
				][0]
				self.assertEqual(found, 0, f"{text[:6]}... is in {table}")
		encrypted = frappe.db.sql(
			"select `password` from `__Auth` where doctype=%s and fieldname in %s",
			("AI Munimji Settings", ("telegram_bot_token", "telegram_webhook_secret")),
		)
		self.assertEqual(len(encrypted), 2)
		self.assertTrue(
			all(TOKEN not in row[0] and secret not in row[0] for row in encrypted), "both are kept encrypted"
		)

	def test_a_telegram_that_is_down_is_reported_without_the_token(self):
		self.telegram.fail.append(
			("getMe", 401, {"ok": False, "error_code": 401, "description": f"Unauthorized {TOKEN}"})
		)
		frappe.set_user(self.tg_manager)
		out = api.connect_bot()
		self.assertFalse(out["ok"])
		self.assertIn("Unauthorized", out["message"])
		self.assertNotIn(TOKEN, out["message"])

	def test_the_requests_to_telegram_go_to_the_configured_address_with_the_token_in_it_only(self):
		self.assertEqual(config.api_base(), "https://api.telegram.org")
		frappe.set_user(self.tg_manager)
		api.connect_bot()
		self.assertTrue(self.telegram.token_seen_in, "the token is the address's, and only the address's")
		for _method, payload, _timeout in self.telegram.calls:
			self.assertNotIn(TOKEN, str(payload))


class TestTheSettingsButtons(TelegramCase):
	def test_only_a_manager_may_connect_the_bot_or_test_it(self):
		for user in (self.alice, self.tg_viewer, "Guest"):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				api.connect_bot()
			with self.assertRaises(frappe.PermissionError):
				api.send_test()
		frappe.set_user(self.alice)
		with self.assertRaises(frappe.PermissionError):
			api.status()

	def test_connecting_the_bot_keeps_its_name_and_registers_the_webhook_with_the_secret(self):
		from unittest import mock

		self.switch_telegram(True, username="")
		frappe.set_user(self.tg_manager)
		with mock.patch.object(
			config,
			"webhook_url",
			lambda: "https://erp.example.com/api/method/ai_munimji.telegram.webhook.receive",
		):
			out = api.connect_bot()
		self.assertTrue(out["ok"], out)
		self.assertEqual(frappe.db.get_single_value("AI Munimji Settings", "telegram_bot_username"), BOT)
		[hook] = self.telegram.of("setWebhook")
		self.assertEqual(
			hook["url"], "https://erp.example.com/api/method/ai_munimji.telegram.webhook.receive"
		)
		self.assertEqual(hook["secret_token"], config.webhook_secret())
		self.assertEqual(hook["allowed_updates"], ["callback_query", "message"])
		self.assertIn(f"@{BOT}", out["message"])

	def test_a_site_without_https_is_told_what_to_do(self):
		frappe.set_user(self.tg_manager)
		out = api.connect_bot()
		self.assertFalse(out["ok"], "a test site is http://")
		self.assertIn("public HTTPS address", out["message"])
		self.assertIn("Polling", out["message"])

	def test_polling_clears_the_webhook_and_starts_the_loop(self):
		self.switch_telegram(True, mode="Polling")
		self.telegram.webhook = "https://old.example.com/hook"
		frappe.set_user(self.tg_manager)
		out = api.connect_bot()
		self.assertTrue(out["ok"], out)
		self.assertEqual(len(self.telegram.of("deleteWebhook")), 1)
		self.assertIsNone(self.telegram.webhook)
		self.assertTrue(
			[
				c
				for c in self.enqueued.call_args_list
				if c.args and c.args[0] == "ai_munimji.telegram.jobs.poll"
			],
			"the loop was queued",
		)

	def test_the_test_message_needs_the_managers_own_chat(self):
		frappe.set_user(self.tg_manager)
		self.assertIn("not connected yet", api.send_test()["message"])
		self.connect("manager")
		frappe.set_user(self.tg_manager)
		out = api.send_test()
		self.assertTrue(out["ok"], out)
		self.assertIn("test message", self.telegram.texts(self.CHAT["manager"])[-1])

	def test_the_status_says_how_updates_arrive_and_how_many_are_connected(self):
		self.connect("alice")
		frappe.set_user(self.tg_manager)
		rows = dict(api.status()["rows"])
		self.assertEqual(
			(rows["Telegram"], rows["Updates arrive by"], rows["People connected"]), ("on", "webhook", "1")
		)
		self.assertEqual(rows["Bot"], f"@{BOT}")


class TestTheLinkRecordRefusesWhatIsNotAChat(IntegrationTestCase):
	def test_a_group_or_channel_id_is_not_a_link(self):
		frappe.set_user("Administrator")
		for chat in ("-100123456", "@priya", "abc", ""):
			with self.assertRaises(frappe.ValidationError, msg=chat):
				frappe.get_doc({"doctype": LINK, "user": "Administrator", "chat_id": chat}).insert(
					ignore_permissions=True
				)
		frappe.db.rollback()
