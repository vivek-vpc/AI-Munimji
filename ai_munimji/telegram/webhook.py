"""The address Telegram calls with a button press or a message: /api/method/ai_munimji.telegram.webhook.receive

It is the one method of the app that a stranger can call, so it does nothing at all until the call has proved who it is: Telegram sends a secret in a header with every call (the site gave it
to Telegram when the bot was connected), and a call without it, or with another, is refused before anything is read, claimed or written. The secret is compared in constant time.
Only then does it become the system (a guest has no rights, and the work needs the system mode for the ledger of updates already seen) and hand the update to inbound.py, which
acts as the person the chat belongs to. A verified call always gets an answer of "ok": Telegram sends an update again until it does, and a person whose answer failed is told so in the chat.
"""

import hmac

import frappe
from frappe import _

from ai_munimji.telegram import config, inbound

HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_BODY = 64 * 1024  # an update is a few hundred bytes


def verify_secret() -> None:
	"""Refuses the call (403) unless Telegram is switched on here and the header holds the site's secret."""
	expected = config.webhook_secret() if config.on() else ""
	request = frappe.local.request if hasattr(frappe.local, "request") else None
	got = (request.headers.get(HEADER) if request is not None else "") or ""
	if not expected or not hmac.compare_digest(got.encode(), expected.encode()):
		frappe.throw(_("Not allowed"), frappe.PermissionError)


# nosemgrep: guest-whitelisted-method - the one method a stranger can call: its first statement refuses any call without Telegram's secret (tests/test_rules.py GUEST_ENDPOINTS)
@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive() -> dict:
	verify_secret()
	request = frappe.local.request
	update = None
	if request is not None and (request.content_length or 0) <= MAX_BODY:
		update = request.get_json(silent=True)
	if not isinstance(update, dict):
		return {"ok": True}
	# nosemgrep: frappe-setuser - Administrator only after verify_secret() has proved the call came from Telegram, and Guest again after (tests/test_rules.py allows this in receive only)
	frappe.set_user("Administrator")
	try:
		inbound.handle_update(update)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title="AI Munimji: an update from Telegram could not be handled",
			message=config.hide_secrets(frappe.get_traceback()),
		)
	finally:
		# nosemgrep: frappe-setuser - Administrator only after verify_secret() has proved the call came from Telegram, and Guest again after (tests/test_rules.py allows this in receive only)
		frappe.set_user("Guest")
	return {"ok": True}
