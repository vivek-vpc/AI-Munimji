"""What the Telegram tests share: a pretend Telegram, and a site with Telegram switched on and three people ready to connect.

`FakeTelegram` stands where the app's transport stands (telegram/transport.py): it is given every call the engine's channel makes, records it, and answers as Telegram does. No network is used.
The tests reach the app the way Telegram does: an update goes to `inbound.handle_update`, which is what the webhook and the polling loop both call.
"""

import itertools
import json
from typing import ClassVar

import frappe
from ai_munimji_engine.core.approvals.channels.base import encode_action

from ai_munimji.stores import locks
from ai_munimji.telegram import inbound, links, transport
from ai_munimji.tests.helpers import APPROVER_ROLES, make_user
from ai_munimji.tests.test_vendor_comparison import FlowCase

TOKEN = "123456789:AAFakeTokenForTheTestsOnly_xyz"
BOT = "munimji_test_bot"
UPDATE_IDS = itertools.count(1000)


class Response:
	def __init__(self, body: dict, status: int = 200):
		self.body, self.status_code = body, status

	def json(self):
		return self.body


class FakeTelegram:
	"""Records every call as (method, payload, timeout) and answers like Telegram. `fail` is a list of (method, status, body) used once each, in order."""

	def __init__(self):
		self.calls: list[tuple[str, dict, float]] = []
		self.fail: list[tuple[str, int, dict]] = []
		self.updates: list[dict] = []
		self.webhook: str | None = None
		self.last_id = 500
		self.token_seen_in: list[str] = []

	def post(self, url, json=None, timeout=15):
		method = url.rsplit("/", 1)[1]
		if TOKEN in url and TOKEN not in self.token_seen_in:
			self.token_seen_in.append(TOKEN)
		self.calls.append((method, json or {}, timeout))
		for i, (wanted, status, body) in enumerate(self.fail):
			if wanted == method:
				self.fail.pop(i)
				return Response(body, status)
		if method == "sendMessage":
			self.last_id += 1
			return Response({"ok": True, "result": {"message_id": self.last_id}})
		if method == "getMe":
			return Response({"ok": True, "result": {"username": BOT, "first_name": "Munimji"}})
		if method == "getUpdates":
			batch, self.updates = self.updates, []
			return Response({"ok": True, "result": batch})
		if method == "getWebhookInfo":
			return Response({"ok": True, "result": {"url": self.webhook or "", "pending_update_count": 0}})
		if method == "setWebhook":
			self.webhook = json["url"]
		if method == "deleteWebhook":
			self.webhook = None
		return Response({"ok": True, "result": True})

	def of(self, method: str) -> list[dict]:
		return [payload for name, payload, _timeout in self.calls if name == method]

	def sent(self, chat) -> list[dict]:
		return [p for p in self.of("sendMessage") if str(p.get("chat_id")) == str(chat)]

	def texts(self, chat) -> list[str]:
		return [p["text"] for p in self.sent(chat)]

	def toasts(self) -> list[str]:
		return [p.get("text", "") for p in self.of("answerCallbackQuery")]

	def buttons(self, payload: dict) -> list[tuple[str, str]]:
		"""(label, action) of each button of a message sent with buttons."""
		rows = (payload.get("reply_markup") or {}).get("inline_keyboard") or []
		return [(b["text"], b["callback_data"].split("|")[2]) for row in rows for b in row]

	def request_messages(self, chat) -> list[dict]:
		return [p for p in self.sent(chat) if p.get("reply_markup", {}).get("inline_keyboard")]


def message(chat, text, reply_to=None, update_id=None):
	body = {
		"message_id": 7,
		"text": text,
		"from": {"id": int(chat), "is_bot": False, "first_name": "Priya"},
		"chat": {"id": int(chat), "type": "private"},
	}
	if reply_to is not None:
		body["reply_to_message"] = {"message_id": int(reply_to)}
	return {"update_id": update_id or next(UPDATE_IDS), "message": body}


def press(chat, approval_id, action, update_id=None):
	return {
		"update_id": update_id or next(UPDATE_IDS),
		"callback_query": {
			"id": f"cq{next(UPDATE_IDS)}",
			"from": {"id": int(chat)},
			"data": encode_action(approval_id, action),
		},
	}


class TelegramCase(FlowCase):
	"""A site with Telegram on, a fake Telegram, and `self.alice` (an approver), `self.bob` (another approver), `self.viewer`, `self.manager`. Nobody is connected yet: `connect` does it."""

	CHAT: ClassVar[dict[str, str]] = {"alice": "1001", "bob": "1002", "viewer": "1003", "manager": "1004"}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.alice = make_user("tg.alice@example.com", APPROVER_ROLES)
		cls.bob = make_user("tg.bob@example.com", APPROVER_ROLES)
		cls.tg_viewer = make_user("tg.viewer@example.com", ("Munimji Viewer",))
		cls.tg_manager = make_user("tg.manager@example.com", ("Munimji Manager", *APPROVER_ROLES))

	def setUp(self):
		super().setUp()
		self.telegram = FakeTelegram()
		from unittest import mock

		self.real_http = transport.Http
		mock.patch.object(transport, "Http", lambda: self.telegram).start()
		# a lease commits what is pending, and these tests' own rollback must still take it all back (the lease itself is shown in test_telegram_flow.TestOneDeliveryAtATime)
		self.leases = mock.patch.multiple(
			locks,
			lease=mock.Mock(return_value=True),
			release=mock.Mock(return_value=None),
			renew=mock.Mock(return_value=None),
		)
		self.leases.start()
		frappe.cache.delete_keys(
			"ai_munimji:telegram:*"
		)  # the cache outlives a test: no code, no throttle and no question from an earlier one
		transport.reset_breaker()
		self.switch_telegram(True)

	def switch_telegram(self, on: bool, mode: str = "Webhook", username: str = BOT):
		frappe.set_user("Administrator")
		page = frappe.get_doc("AI Munimji Settings")
		page.telegram_enabled = 1 if on else 0
		page.telegram_mode = mode
		if on:
			page.telegram_bot_token = TOKEN
		page.telegram_bot_username = username
		page.save()
		frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")

	def update(self, payload: dict) -> str:
		"""An update from Telegram, as the webhook and the poller hand it over (as the system)."""
		frappe.set_user("Administrator")
		return inbound.handle_update(payload)

	def connect(self, who: str = "alice") -> str:
		"""Connect a person's chat the way a person does: the code from the Desk, then /start <code> in the chat. Returns the chat id."""
		user = {"alice": self.alice, "bob": self.bob, "viewer": self.tg_viewer, "manager": self.tg_manager}[
			who
		]
		chat = self.CHAT[who]
		frappe.set_user("Administrator")
		code = links.issue_code(user)
		self.assertEqual(self.update(message(chat, f"/start {code}")), "linked", who)
		return chat

	def press_as(self, who: str, approval_id: str, action: str):
		return self.update(press(self.CHAT[who], approval_id, action))

	def say_as(self, who: str, text: str, reply_to=None):
		return self.update(message(self.CHAT[who], text, reply_to))

	def decision_of(self, approval_id: str):
		from ai_munimji.stores import frappe_core_stores

		record = frappe_core_stores(system=True).approvals.get(approval_id)
		return json.loads(record["decision_json"]) if record and record["decision_json"] else None

	def desk_answer(self, approval_id: str, action: str, who: str = "alice", **params) -> dict:
		user = {"alice": self.alice, "bob": self.bob}[who]
		return self.answer(approval_id, action, user, **params)

	def deliver(self) -> dict:
		"""What the queued delivery job does (it runs as Administrator)."""
		from ai_munimji.telegram import jobs as telegram_jobs

		frappe.set_user("Administrator")
		return telegram_jobs.deliver_new()


__all__ = ["BOT", "TOKEN", "FakeTelegram", "TelegramCase", "message", "press"]
