"""Which Telegram chat is which person.

A person connects their chat themselves: in the Desk they press Connect Telegram and get a link to the bot with a one-time code in it (`t.me/<bot>?start=<code>`). Opening it and pressing Start
makes Telegram send the bot `/start <code>`, and that is the proof that the person at the Desk and the person in the chat are one: nobody has to type a chat id, and a chat id nobody
connected is never trusted. The code lives ten minutes in the site's cache, is stored as a hash and works once.

A chat belongs to one person and a person has one chat. What is kept is the Munimji Telegram Link: the user, the chat id, whether requests are sent there, and when it was connected.

This module writes the link with `ignore_permissions`, as the bot: the person's session is not the one that is running (the webhook and the poller run as the system, and a person
has no right to create a link for someone else). tests/test_rules.py names the functions that may.
"""

import hashlib
import secrets
from dataclasses import dataclass

import frappe
from ai_munimji_engine.core.approvals.models import Recipient, RecipientChannel
from frappe import _

LINK = "Munimji Telegram Link"
REQUEST = "Munimji Approval Request"
CODE_SECONDS = 600
CODE_PREFIX = "ai_munimji:telegram:code:"
OPEN_CODE_PREFIX = "ai_munimji:telegram:opencode:"
CODE_SHAPE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def looks_like_a_code(text: str) -> bool:
	"""What the bot is sent after /start: only the characters a code is made of, and no more than Telegram allows."""
	return 8 <= len(text) <= 64 and all(c in CODE_SHAPE for c in text)


def _key(code: str) -> str:
	return CODE_PREFIX + hashlib.sha256(code.encode()).hexdigest()


def may_connect(user: str) -> bool:
	"""Whether this user can be sent requests and answer them: enabled, and allowed by Frappe to approve (which also asks for the right to create a Purchase Order)."""
	return bool(
		user
		and user not in ("Guest", "Administrator")
		and frappe.db.get_value("User", user, "enabled")
		and frappe.has_permission(REQUEST, "approve", user=user)
	)


def forget_open_code(user: str) -> None:
	"""The code this user asked for and has not used stops working."""
	previous = frappe.cache.get_value(OPEN_CODE_PREFIX + user)
	if previous:
		frappe.cache.delete_value(previous)
	frappe.cache.delete_value(OPEN_CODE_PREFIX + user)


def issue_code(user: str) -> str:
	"""A fresh one-time code for this user; the one they asked for before stops working."""
	code = secrets.token_urlsafe(9)
	forget_open_code(user)
	frappe.cache.set_value(_key(code), user, expires_in_sec=CODE_SECONDS)
	frappe.cache.set_value(OPEN_CODE_PREFIX + user, _key(code), expires_in_sec=CODE_SECONDS)
	return code


@dataclass
class Redeemed:
	user: str | None  # who was connected, or None
	sentence: str  # what the chat is told
	left: str | None = None  # the chat this person had before, which will no longer get requests


def redeem(code: str, chat_id: str) -> Redeemed:
	"""The person who made `code` is now the person in chat `chat_id`. The code is spent whatever happens."""
	key = _key(code)
	user = frappe.cache.get_value(key)
	frappe.cache.delete_value(key)
	if not user:
		return Redeemed(
			None,
			_(
				"That link has expired or was already used. Open AI Munimji in your browser and press Connect Telegram again."
			),
		)
	frappe.cache.delete_value(OPEN_CODE_PREFIX + user)
	if not may_connect(user):
		return Redeemed(
			None,
			_(
				"Your user cannot answer requests (it needs the Munimji Approver role), so Telegram was not connected."
			),
		)
	taken = frappe.db.get_value(LINK, {"chat_id": chat_id}, "user")
	if taken and taken != user:
		return Redeemed(
			None,
			_(
				"This Telegram chat is already connected to another AI Munimji user. They have to disconnect it first."
			),
		)
	return _write(user, chat_id)


def _write(user: str, chat_id: str) -> Redeemed:
	from ai_munimji_engine.core.common import iso, utcnow

	now = frappe.utils.now_datetime()
	left = None
	if frappe.db.exists(LINK, user):
		link = frappe.get_doc(LINK, user)
		if link.chat_id and link.chat_id != chat_id:
			left = link.chat_id
		link.update({"chat_id": chat_id, "enabled": 1, "linked_on": now, "since": iso(utcnow())})
		link.save(ignore_permissions=True)
	else:
		link = frappe.get_doc(
			{
				"doctype": LINK,
				"user": user,
				"chat_id": chat_id,
				"enabled": 1,
				"linked_on": now,
				"since": iso(utcnow()),
			}
		).insert(ignore_permissions=True)
		link.db_set("owner", user, update_modified=False)  # the person owns their link, whoever made it
	return Redeemed(
		user,
		_("Connected. Requests that need your answer will arrive here, with buttons."),
		left,
	)


def user_for_chat(chat_id: str) -> str | None:
	"""The person a chat is connected to, if requests are sent there and the user is still enabled and still allowed to answer."""
	user = frappe.db.get_value(LINK, {"chat_id": str(chat_id), "enabled": 1}, "user")
	return user if user and may_connect(user) else None


def recipient(user: str, chat_id: str) -> Recipient:
	name = frappe.db.get_value("User", user, "full_name") or user
	return Recipient(
		id=user, name=name, roles=["approver"], channels=[RecipientChannel(type="telegram", address=chat_id)]
	)


def recipient_for_chat(chat_id: str) -> Recipient | None:
	user = user_for_chat(chat_id)
	return recipient(user, str(chat_id)) if user else None


def recipients() -> list[Recipient]:
	"""Everyone who is sent requests here: connected, switched on, enabled, and allowed to answer."""
	people = []
	for row in frappe.db.get_values(LINK, {"enabled": 1}, ["user", "chat_id"], as_dict=True):
		if may_connect(row.user):
			people.append(recipient(row.user, row.chat_id))
	return people


def connected_since(user: str) -> str:
	"""When this person's chat was connected, as the engine writes times (ISO, UTC); requests made before that are not sent to them."""
	return frappe.db.get_value(LINK, user, "since") or ""


def chat_of(user: str) -> str | None:
	return frappe.db.get_value(LINK, {"user": user, "enabled": 1}, "chat_id")


def count() -> int:
	return frappe.db.count(LINK, {"enabled": 1})


def on_user_trash(doc, method=None) -> None:
	"""A user who is deleted takes their Telegram link with them: the chat id is theirs and has no other use (a hook of the User DocType)."""
	frappe.db.delete(LINK, {"user": doc.name})
