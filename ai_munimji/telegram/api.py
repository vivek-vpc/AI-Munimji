"""The buttons of the Settings page (for the Munimji Managers) and of the Connect Telegram dialog (for the people who answer requests).

Every method checks who is asking as its first statement. None is open to guests: the one method a stranger can call is webhook.receive, which proves who is calling before it does anything.
No sentence here, and no answer, holds the bot token: it is a password. What Telegram says in an error is passed through the engine's channel, which has already hidden it.
"""

import frappe
from frappe import _

from ai_munimji.telegram import channel as channel_module
from ai_munimji.telegram import config, jobs, links, transport

LINKERS = ("Munimji Approver", "Munimji Manager", "System Manager")
MANAGERS = ("Munimji Manager", "System Manager")
SETTINGS = config.SETTINGS


# ------------------------------------------------------------------ the Connect Telegram dialog: the people who answer requests
@frappe.whitelist(methods=["POST"])
def connect() -> dict:
	"""A link to the bot with a one-time code, valid for ten minutes. Opening it and pressing Start in Telegram connects that chat to the signed-in person."""
	frappe.only_for(LINKERS)
	user = frappe.session.user
	if not config.enabled():
		return {
			"ok": False,
			"message": _(
				"Telegram is not switched on for this site. Ask a Munimji Manager to switch it on in AI Munimji Settings."
			),
		}
	bot = config.page().telegram_bot_username
	if not bot:
		return {
			"ok": False,
			"message": _(
				"The bot is not connected yet. A Munimji Manager has to press “Connect the bot” in AI Munimji Settings first."
			),
		}
	if not links.may_connect(user):
		return {
			"ok": False,
			"message": _(
				"This user cannot answer requests, so there is nothing to send to Telegram. Use your own user (the Munimji Approver role)."
			),
		}
	code = links.issue_code(user)
	return {
		"ok": True,
		"link": f"https://t.me/{bot}?start={code}",
		"bot": f"@{bot}",
		"expires_in": links.CODE_SECONDS,
		"message": _(
			"Open the link on the phone or computer where you use Telegram and press Start. It works once, for ten minutes."
		),
	}


@frappe.whitelist(methods=["GET", "POST"])
def connection() -> dict:
	"""Whether the signed-in person's Telegram is connected (the dialog asks until it is)."""
	frappe.only_for(LINKERS)
	return {"connected": bool(links.chat_of(frappe.session.user)), "on": config.on()}


@frappe.whitelist(methods=["POST"])
def disconnect(user: str | None = None) -> dict:
	"""Stop sending requests to a Telegram chat: the signed-in person's own, or (a Munimji Manager) another person's. The chat itself is not touched."""
	frappe.only_for(LINKERS)
	target = user or frappe.session.user
	if target != frappe.session.user:
		frappe.only_for(MANAGERS)
	if frappe.db.exists(links.LINK, target):
		frappe.delete_doc(links.LINK, target)
		if target == frappe.session.user:
			return {
				"ok": True,
				"message": _("Telegram is disconnected. Requests are no longer sent to your chat."),
			}
		return {
			"ok": True,
			"message": _(
				"Telegram is disconnected for {0}. Requests are no longer sent to their chat."
			).format(target),
		}
	return {"ok": True, "message": _("That Telegram was not connected.")}


# ------------------------------------------------------------------ the Settings page: the Munimji Managers
def _live_rows(channel) -> list[list[str]]:
	"""What Telegram says about the webhook (one call). Nothing here holds the token."""
	rows = []
	info = channel.webhook_info()
	if info.get("url"):
		rows.append([_("Telegram calls"), info["url"]])
	else:
		rows.append([_("Telegram calls"), _("nothing: no webhook is registered (right for polling)")])
	rows.append([_("Updates waiting at Telegram"), str(info.get("pending_update_count", 0))])
	if info.get("last_error_message"):
		rows.append([_("Telegram's last delivery error"), str(info["last_error_message"])[:200]])
	return rows


def _rows(live=None) -> list[list[str]]:
	page = config.page()
	rows = [
		[_("Telegram"), _("on") if page.telegram_enabled else _("off")],
		[
			_("Bot"),
			f"@{page.telegram_bot_username}" if page.telegram_bot_username else _("not connected yet"),
		],
		[_("Updates arrive by"), _("polling") if config.mode() == "polling" else _("webhook")],
		[_("People connected"), str(links.count())],
	]
	if config.mode() == "polling":
		from ai_munimji.stores import locks

		rows.append(
			[_("The polling loop"), _("running") if locks.held(jobs.POLL_LEASE) else _("not running")]
		)
	if transport.breaker_open():
		rows.append([_("Telegram"), _("not answering a moment ago; not tried again for a minute")])
	return rows + (live or [])


@frappe.whitelist(methods=["GET", "POST"])
def status() -> dict:
	"""What the Settings page shows about Telegram, from this site only (no call to Telegram)."""
	frappe.has_permission(SETTINGS, "read", throw=True)
	return {"rows": _rows()}


@frappe.whitelist(methods=["POST"])
def connect_bot() -> dict:
	"""The Connect the bot button: asks Telegram who the token belongs to, keeps the bot's name, and makes Telegram send updates here (a webhook) or starts the loop that fetches them (polling)."""
	frappe.only_for(MANAGERS)
	channel = channel_module.build_channel()
	if channel is None:
		return {
			"ok": False,
			"message": _(
				"Switch Telegram on and enter the bot token, then save the page, and press this again."
			),
		}
	transport.reset_breaker()
	try:
		bot = channel.me()
	except Exception as exc:
		return {"ok": False, "message": _("Telegram did not accept the bot token: {0}").format(str(exc))}
	frappe.db.set_single_value(SETTINGS, "telegram_bot_username", bot.get("username") or "")
	frappe.clear_document_cache(SETTINGS, SETTINGS)
	if config.mode() == "webhook" and not config.webhook_secret():
		return {
			"ok": False,
			"message": _(
				"The webhook secret has not been made yet: save the page once more, then press this again."
			),
		}
	try:
		if config.mode() == "webhook":
			channel.set_webhook(config.webhook_url())
			started = _("Telegram will call {0}.").format(config.webhook_url())
		else:
			channel.delete_webhook()
			started = _("A loop that asks Telegram for updates is {0}.").format(
				_("started") if jobs.ensure_poller() == "queued" else _("already running")
			)
		live = _live_rows(channel)
	except ValueError:
		return {
			"ok": False,
			"message": _(
				"A webhook needs this site's public HTTPS address, and this site is {0}. Choose Polling on the page, or put the site behind HTTPS."
			).format(frappe.utils.get_url()),
		}
	except Exception as exc:
		return {"ok": False, "message": _("Telegram refused: {0}").format(str(exc))}
	return {
		"ok": True,
		"message": _("Connected to @{0}. {1} People connect their own chat with Connect Telegram.").format(
			bot.get("username"), started
		),
		"rows": _rows(live),
	}


@frappe.whitelist(methods=["POST"])
def send_test() -> dict:
	"""A test message to the signed-in manager's own chat."""
	frappe.only_for(MANAGERS)
	chat = links.chat_of(frappe.session.user)
	if not chat:
		return {
			"ok": False,
			"message": _(
				"Your own Telegram is not connected yet: press Connect Telegram in AI Munimji, then try again."
			),
		}
	channel = channel_module.build_channel()
	if channel is None:
		return {"ok": False, "message": _("Telegram is switched off, or has no bot token.")}
	result = channel.send_text(
		chat,
		"AI Munimji: this is a test message. If you can read it, Telegram is connected and requests will arrive here.",
	)
	if result.ok:
		return {"ok": True, "message": _("A test message was sent to your chat.")}
	return {"ok": False, "message": _("The test message could not be sent: {0}").format(result.error)}
