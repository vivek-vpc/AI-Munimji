"""The one place where the app talks to the network.

Everything else of Telegram (what to send, what an answer means) is the engine's and makes no call; the engine's channel is given this object as its `http`. tests/test_nothing_leaves.py names
this module as the one exception to "the app imports no network library", and its runtime test shows that with Telegram on the only address ever called is the one in the site's configuration.

- It refuses redirects: the bot token is in every address, and a server it was sent to could point it somewhere else.
- It never raises the library's own error, because that error quotes the address and the address holds the token: it raises a plain ConnectionError that names only the kind of failure.
- After three failures in a row it stops trying for a minute (a breaker kept in the site's cache), so that a Telegram that is down does not hold up every Desk answer by its timeout.
"""

import frappe
import requests

BREAKER = "ai_munimji:telegram:breaker"
FAILURES = "ai_munimji:telegram:failures"
FAILURES_TO_OPEN = 3
OPEN_SECONDS = 60


def breaker_open() -> bool:
	return bool(frappe.cache.get_value(BREAKER))


def reset_breaker() -> None:
	frappe.cache.delete_value(BREAKER)
	frappe.cache.delete_value(FAILURES)


class Http:
	"""What the engine's channel needs: post(url, json=..., timeout=...) that answers with an object having status_code and json()."""

	def __init__(self) -> None:
		self.session = requests.Session()
		self.session.max_redirects = 0

	def post(self, url: str, json: dict | None = None, timeout: float = 15):
		if breaker_open():
			raise ConnectionError(
				"Telegram could not be reached a moment ago, so it is not tried again for a minute"
			)
		try:
			response = self.session.post(url, json=json, timeout=timeout, allow_redirects=False)
		except requests.RequestException as exc:
			self._failed()
			raise ConnectionError(type(exc).__name__) from None
		frappe.cache.delete_value(FAILURES)
		return response

	@staticmethod
	def _failed() -> None:
		count = int(frappe.cache.get_value(FAILURES) or 0) + 1
		if count >= FAILURES_TO_OPEN:
			frappe.cache.set_value(BREAKER, 1, expires_in_sec=OPEN_SECONDS)
			frappe.cache.delete_value(FAILURES)
		else:
			frappe.cache.set_value(FAILURES, count, expires_in_sec=OPEN_SECONDS)
