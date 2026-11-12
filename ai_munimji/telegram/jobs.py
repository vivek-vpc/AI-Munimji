"""The jobs of Telegram. Each runs as Administrator (the system), as the first thing it does: Frappe runs a queued job as the person who queued it, and these read and write in the system mode.

  deliver_new   sends the waiting requests to the people who were not sent them (outbox.py); queued by `outbox.nudge`
  housekeeping  every few minutes: the same delivery as a safety net, the failed sends tried again (up to the engine's five), the reminders, and the polling loop kept alive. Scheduled (schedule.py)
  poll          the polling loop, for a site Telegram cannot call: asks Telegram for updates for a few minutes at a time and handles each as the webhook would. One at a time (a lease); it queues
                its successor as it ends, and the housekeeping starts one if none is running

All of them do nothing while Telegram is switched off.
"""

import time
from contextlib import contextmanager

import frappe

from ai_munimji import jobs
from ai_munimji.stores import locks
from ai_munimji.telegram import channel, config, inbound, outbox

POLL = "ai_munimji.telegram.jobs.poll"
POLL_LEASE = "telegram_poll"
OUTBOX_LEASE = "telegram_outbox"
OUTBOX_LEASE_MINUTES = (
	5  # a delivery of a few hundred messages takes seconds; a holder that died is taken for dead after this
)
POLL_QUEUE = "long"
LOOP_SECONDS = 9 * 60  # how long one poll job keeps asking before it queues its successor
LONG_POLL_SECONDS = 25  # Telegram holds a request this long when it has nothing to say
LEASE_MINUTES = 2  # renewed after every request to Telegram: a loop that stops renewing is taken for dead
POLL_TIMEOUT = LOOP_SECONDS + 3 * 60
LOG = "ai_munimji"


def deliver_new() -> dict:
	# nosemgrep: frappe-setuser - a queued job runs as whoever queued it, and these read and write in the system mode, which is Administrator's alone (tests/test_rules.py names the three jobs)
	frappe.set_user("Administrator")
	if not config.enabled():
		return {"ran": False, "why": "Telegram is off", "sent": 0}
	with sending() as taken:
		if not taken:
			return {"ran": False, "why": "another delivery is running", "sent": 0}
		return {"ran": True, "sent": outbox.deliver_pending(jobs.system_services(telegram=True))}


def housekeeping() -> dict:
	# nosemgrep: frappe-setuser - a queued job runs as whoever queued it, and these read and write in the system mode, which is Administrator's alone (tests/test_rules.py names the three jobs)
	frappe.set_user("Administrator")
	if not config.enabled():
		return {"ran": False, "why": "Telegram is off"}
	with sending() as taken:
		if not taken:
			return {"ran": False, "why": "another delivery is running"}
		services = jobs.system_services(telegram=True)
		report = {
			"ran": True,
			"sent": outbox.deliver_pending(services),
			"retried": services.approvals.retry_failed_deliveries(),
			"reminded": len(outbox.remind(services)),
		}
	report["poller"] = ensure_poller()
	return report


@contextmanager
def sending():
	"""One delivery at a time. A request is sent to a person when no message of it has been recorded for them, so two runs at once (the queued delivery and the housekeeping) would both find
	it unsent and send it twice. The first takes the lease and the other leaves what is left to the next run; the lease runs out by itself if its holder dies. It commits (a lease must be seen
	at once), so it is taken before anything is written, and released, with a commit, when the work is done. Yields whether it was taken."""
	holder = frappe.generate_hash(length=10)
	if not locks.lease(OUTBOX_LEASE, holder, OUTBOX_LEASE_MINUTES):
		yield False
		return
	try:
		yield True
	finally:
		locks.release(OUTBOX_LEASE, holder)


def ensure_poller() -> str:
	"""Start the polling loop if the site is set to poll and none is running. Returns what it did: 'not wanted', 'running' or 'queued'."""
	if not (config.enabled() and config.mode() == "polling"):
		return "not wanted"
	if locks.held(POLL_LEASE):
		return "running"
	frappe.enqueue(
		POLL, queue=POLL_QUEUE, timeout=POLL_TIMEOUT, job_id="ai_munimji:telegram_poll", deduplicate=True
	)
	return "queued"


def wanted() -> bool:
	"""The loop goes on while Telegram is on and in polling mode (the page may have been changed meanwhile)."""
	frappe.clear_document_cache(config.SETTINGS, config.SETTINGS)
	return config.enabled() and config.mode() == "polling"


def poll() -> dict:
	# nosemgrep: frappe-setuser - a queued job runs as whoever queued it, and these read and write in the system mode, which is Administrator's alone (tests/test_rules.py names the three jobs)
	frappe.set_user("Administrator")
	if not wanted():
		return {"ran": False, "why": "Telegram is not set to polling"}
	holder = frappe.generate_hash(length=10)
	if not locks.lease(POLL_LEASE, holder, LEASE_MINUTES):
		return {"ran": False, "why": "another poller is running"}
	handled = 0
	try:
		telegram = channel.build_channel()
		_clear_webhook(telegram)  # Telegram refuses getUpdates while a webhook is set
		deadline = time.monotonic() + LOOP_SECONDS
		while time.monotonic() < deadline and wanted():
			locks.renew(POLL_LEASE, holder, LEASE_MINUTES)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit - the renewal is kept at once: the lease is what tells the housekeeping that a loop is alive
			try:
				events = telegram.poll_once(timeout=LONG_POLL_SECONDS)
			except Exception as exc:  # Telegram was unreachable: wait a little and ask again; the message is already without the token
				frappe.logger(LOG).warning(f"Telegram polling: {exc}")
				time.sleep(5)
				continue
			for event in events:
				handled += _one(telegram, event)
	finally:
		locks.release(POLL_LEASE, holder)
	if wanted():
		frappe.enqueue(
			POLL, queue=POLL_QUEUE, timeout=POLL_TIMEOUT, job_id="ai_munimji:telegram_poll", deduplicate=True
		)
	return {"ran": True, "handled": handled}


def _clear_webhook(telegram) -> None:
	try:
		telegram.delete_webhook()
	except Exception as exc:
		frappe.logger(LOG).warning(f"Telegram polling: the webhook could not be cleared ({exc})")


def _one(telegram, event) -> int:
	"""One update, handled and kept. A failure takes back only this update's work; the person is told, and the loop goes on."""
	try:
		inbound.handle_event(telegram, event)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - one update at a time: what it did is kept, whatever the next one does
		return 1
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title="AI Munimji: an update from Telegram could not be handled",
			message=config.hide_secrets(frappe.get_traceback()),
		)
		try:
			telegram.send_text(
				event.sender,
				"I could not handle that just now. Nothing was changed. Please try again in a moment.",
			)
		except Exception:
			frappe.logger(LOG).warning("Telegram polling: the person could not be told either", exc_info=True)
		return 0
