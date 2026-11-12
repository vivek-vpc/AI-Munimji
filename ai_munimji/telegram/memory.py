"""What the Telegram parts remember between two requests. The site has several processes, so it cannot be kept in one of them: it is kept in the site's cache (Redis), and every value
expires by itself. Nothing here is a record: losing it costs a person one more tap or one more message, never a decision.

The values are plain text or numbers, not pickled objects, and they hold no secret.
"""

import json

import frappe
from ai_munimji_engine.runtime import Awaiting, ItemContext

PREFIX = "ai_munimji:telegram:"
ASKED_FOR_SECONDS = (
	11 * 60
)  # a person has ten minutes to answer the bot's question (typed_answers.WAIT_SECONDS); the cache keeps it a minute longer, the answer checks the time


def _cache():
	return frappe.cache


class CacheThrottle:
	"""One answer per chat per `every` seconds, whichever process answers (the engine's channel asks `allow` before it replies to a stranger)."""

	def __init__(self, every: float = 30.0) -> None:
		self.every = every

	def allow(self, key: str) -> bool:
		name = f"{PREFIX}throttle:{key}"
		if _cache().get_value(name):
			return False
		_cache().set_value(name, 1, expires_in_sec=max(1, int(self.every)))
		return True


class CacheOffset:
	"""Where polling has got to. If it is lost Telegram hands out again what was not confirmed, and the inbound ledger recognises it."""

	NAME = f"{PREFIX}offset"

	def get(self) -> int:
		return int(_cache().get_value(self.NAME) or 0)

	def set(self, value: int) -> None:
		_cache().set_value(self.NAME, int(value), expires_in_sec=30 * 24 * 3600)


class CacheConversationMemory:
	"""What the bot has just asked a person (a quantity, a vendor, yes or no), and what their last answer was about."""

	@staticmethod
	def _key(kind: str, channel: str, sender: str) -> str:
		return f"{PREFIX}{kind}:{channel}:{sender}"

	def expect(self, channel: str, sender: str, awaiting: Awaiting) -> None:
		value = json.dumps(
			{
				"approval_id": awaiting.approval_id,
				"action": awaiting.action,
				"choices": awaiting.choices,
				"until": awaiting.until,
			}
		)
		_cache().set_value(self._key("asked", channel, sender), value, expires_in_sec=ASKED_FOR_SECONDS)

	def take_awaiting(self, channel: str, sender: str) -> Awaiting | None:
		key = self._key("asked", channel, sender)
		raw = _cache().get_value(key)
		if not raw:
			return None
		_cache().delete_value(key)
		try:
			data = json.loads(raw)
			return Awaiting(data["approval_id"], data["action"], list(data["choices"]), float(data["until"]))
		except (ValueError, KeyError, TypeError):
			return None

	def remember_items(self, channel: str, sender: str, context: ItemContext) -> None:
		value = json.dumps({"items": context.items, "until": context.until})
		_cache().set_value(self._key("items", channel, sender), value, expires_in_sec=ASKED_FOR_SECONDS)

	def recall_items(self, channel: str, sender: str) -> ItemContext | None:
		raw = _cache().get_value(self._key("items", channel, sender))
		if not raw:
			return None
		try:
			data = json.loads(raw)
			return ItemContext(list(data["items"]), float(data["until"]))
		except (ValueError, KeyError, TypeError):
			return None
