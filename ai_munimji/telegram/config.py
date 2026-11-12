"""What the AI Munimji Settings page says about Telegram, read in one place."""

import frappe
from frappe.utils.password import get_decrypted_password

SETTINGS = "AI Munimji Settings"
DEFAULT_API = "https://api.telegram.org"
WEBHOOK = "ai_munimji.telegram.webhook.receive"


def page():
	return frappe.get_cached_doc(SETTINGS)


def on() -> bool:
	"""Whether a Munimji Manager has switched Telegram on. A cheap question (no secret is read): the stock check asks it for every request it makes."""
	return bool(page().telegram_enabled)


def token() -> str:
	"""The bot token, as the Password field keeps it (encrypted in the site's database). It is a password: it is never logged, never put in an error and never sent to the page."""
	return get_decrypted_password(SETTINGS, SETTINGS, "telegram_bot_token", raise_exception=False) or ""


def webhook_secret() -> str:
	"""The secret that Telegram sends in a header with every call to the webhook. The page generates it when Telegram is switched on; nobody reads or types it."""
	return get_decrypted_password(SETTINGS, SETTINGS, "telegram_webhook_secret", raise_exception=False) or ""


def hide_secrets(text: str) -> str:
	"""`text` with the bot token and the webhook secret taken out of it, for anything that is written down (an Error Log). Nothing the app raises should hold either, because the transport and
	the engine's channel already keep them out of their errors; this is the last line, for an error nobody thought of."""
	from urllib.parse import quote

	for secret in (token(), webhook_secret()):
		if secret:
			for form in {secret, quote(secret, safe=""), quote(secret)}:
				text = text.replace(form, "<hidden>")
	return text


def enabled() -> bool:
	"""Switched on and given a token."""
	return on() and bool(token())


def mode() -> str:
	"""'webhook' (Telegram calls the site: instant, needs a public HTTPS address) or 'polling' (a job asks Telegram for updates: works behind a router, needs a worker on the long queue)."""
	return "polling" if page().telegram_mode == "Polling" else "webhook"


def api_base() -> str:
	"""Telegram's address. A site's configuration may name another (`ai_munimji_telegram_api_base`), which is how the tests talk to a pretend Telegram; nothing on the page can."""
	return (frappe.conf.get("ai_munimji_telegram_api_base") or DEFAULT_API).rstrip("/")


def webhook_url() -> str:
	return frappe.utils.get_url(f"/api/method/{WEBHOOK}")
