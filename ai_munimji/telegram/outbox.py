"""Requests are sent to Telegram by a job, after they are committed, and never by the code that makes them.

The stock check makes its requests in batches, inside database transactions that lock rows; a call to Telegram inside one would hold those locks for as long as Telegram takes to answer (and for
its timeout when it does not). So the stock check, and the vendor comparison, only ask for a delivery (`nudge`): a job, queued once the transaction has committed, finds the requests that are
waiting and have not been sent to a person, and sends them (`deliver_pending`). The same job is the safety net: the housekeeping runs it every few minutes, so a request is delivered even if the
nudge was lost.

Each message is recorded as a delivery (who, on which channel, with which message id), through the engine's `ApprovalService.resend`: that record is what lets the bot tidy the message up
when the request is answered, tie a person's reply to the request, and retry a send that failed.

A person who connects Telegram is sent the requests made from then on, not the ones that were already waiting: twenty old messages at once would bury the one that matters. Those stay in the Desk.
"""

from datetime import timedelta

import frappe
from ai_munimji_engine.core.common import iso

from ai_munimji.telegram import config, links

JOB = "ai_munimji.telegram.jobs.deliver_new"
JOB_ID = "ai_munimji:telegram_outbox"
WAITING = 200  # the newest waiting requests that are looked at; a site with more waiting than that has a bigger problem than Telegram


def nudge(_record=None) -> None:
	"""Ask for the waiting requests to be sent, once the current transaction is committed. Does nothing while Telegram is off. Cheap and safe to call as often as you like: a delivery
	that is already queued is not queued again. (The argument is there so that this can be a listener of new requests.)"""
	if not config.on():
		return
	frappe.enqueue(JOB, queue="short", job_id=JOB_ID, deduplicate=True, enqueue_after_commit=True)


def waiting_in_order(approvals) -> list:
	"""The waiting requests in the order they were made. The store lists the newest first and, among requests made in the same second, the older one first (an alert and the reorder it
	suggests come from one check, within a second of each other). Sorting stably on the time alone gives oldest first and keeps those ties as they were made; reversing the list instead would
	turn the ties around, and the reorder would reach the chat before the alert."""
	return sorted(approvals.list(status="pending", limit=WAITING), key=lambda record: record.created_at)


def deliver_pending(services) -> int:
	"""Send every waiting request to every connected person who has not been sent it (and was connected before it was made). Returns how many messages were sent. `services` are the system-mode services
	built with Telegram in the router (jobs.system_services(telegram=True))."""
	approvals = services.approvals
	router = approvals.router
	if "telegram" not in router.channels:
		return 0
	sent = 0
	for record in waiting_in_order(approvals):
		already = {(d["recipient_id"], d["channel"]) for d in approvals.store.deliveries(record.id)}
		for recipient, channels in router.targets():
			if links.connected_since(recipient.id) > iso(record.created_at):
				continue
			for chosen in channels:
				if (recipient.id, chosen.type) in already:
					continue
				sent += int(approvals.resend(record, recipient.id, chosen.type, chosen.address))
	return sent


def remind(services) -> list[str]:
	"""The reminder of the engine (ApprovalService.remind_due), sent only to the people who were sent the request: a person who connected later has no message to scroll up to. One nudge
	per `reminder_after_hours`, up to `max_reminders`, from the settings page; it never answers anything."""
	approvals = services.approvals
	channel = approvals.router.channels.get("telegram")
	if channel is None:
		return []
	settings = approvals.system_settings()
	now = approvals.clock()
	reminded = []
	for record in waiting_in_order(approvals):
		if record.reminder_count >= settings.max_reminders or record.kind in approvals.no_reminder_kinds:
			continue
		if now - (record.last_reminder_at or record.created_at) < timedelta(
			hours=settings.reminder_after_hours
		):
			continue
		for delivery in approvals.store.deliveries(record.id, "sent"):
			if delivery["channel"] == "telegram" and delivery["address"]:
				channel.send_reminder(record, delivery["address"])
		approvals.store.add_reminder(record.id, iso(now))
		reminded.append(record.id)
	return reminded
