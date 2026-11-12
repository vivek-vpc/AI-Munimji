"""One update from Telegram, handled as the person it came from.

The webhook and the polling loop both end here, as Administrator (the system). From there:

  * `/start <code>` connects the chat to the person who made the code (links.py). The reply says whether it worked.
  * a chat that is not connected is a stranger: `/start`, `/id` and `/help` tell them their own chat id (the engine's channel, at most one answer per half minute); a button press is refused.
  * a connected chat is the Frappe user it is connected to. The press or message is handled with that user signed in, through the same services as an answer in the Desk
    (`wiring.person_services`): ERPNext is read and written as that person, the records are kept through their roles' permissions, and a Purchase Order is made in their name. What Frappe
    would refuse that user in the Desk it refuses here. The engine's own code does the rest (core/approvals/inbound.py): the decision, the duplicate guard, the questions and the typed answers.

An update that Telegram delivers again is recognised by its id in the system mode, before anything is done, because the ledger belongs to the system and a person has no right to it.
The caller commits (the webhook's request ends in a commit; the poller commits after each update) and rolls back when this raises, which also takes the ledger entry back, so that a delivery that comes again is tried again.
"""

import time
from contextlib import contextmanager

import frappe
from ai_munimji_engine.core.approvals.inbound import process_inbound
from ai_munimji_engine.core.approvals.inbound_ledger import InboundLedger
from ai_munimji_engine.core.approvals.typed_answers import TypedConversation
from frappe import _

from ai_munimji import jobs, next_step, wiring
from ai_munimji.telegram import channel as channel_module
from ai_munimji.telegram import links, memory

NOT_UNDERSTOOD = (
	"I take answers to requests here: use the buttons under a request message, or reply to an order request with a number to change its quantity. "
	"For anything else open AI Munimji in your browser. Nothing was changed."
)


@contextmanager
def as_user(user: str):
	"""Everything inside is done as this user, and the session goes back to what it was."""
	before = frappe.session.user
	# nosemgrep: frappe-setuser - the person a chat is connected to, and back: a press is that person's own answer, with their rights (tests/test_rules.py allows this in as_user only)
	frappe.set_user(user)
	try:
		yield
	finally:
		# nosemgrep: frappe-setuser - the person a chat is connected to, and back: a press is that person's own answer, with their rights (tests/test_rules.py allows this in as_user only)
		frappe.set_user(before)


def start_code(text: str | None) -> str | None:
	"""The code in `/start <code>` (what a link `t.me/<bot>?start=<code>` makes Telegram send), or None."""
	words = (text or "").split()
	if len(words) == 2 and words[0].split("@")[0].lower() == "/start" and links.looks_like_a_code(words[1]):
		return words[1]
	return None


def first_time(event) -> bool:
	"""False when Telegram has delivered this update before (its id was seen). Made in the system mode."""
	if not event.external_id:
		return True
	return InboundLedger(jobs.system_stores().inbound).claim(event.channel, event.external_id)


def handle_update(update: dict, channel=None) -> str:
	"""The update as Telegram sent it. Returns a word for what became of it, for the tests and the log: off, ignored, duplicate, linked, refused_link, stranger, handled."""
	channel = channel or channel_module.build_channel()
	if channel is None:
		return "off"
	outcome = "ignored"
	for event in channel.parse_webhook(update):
		outcome = handle_event(channel, event)
	return outcome


def handle_event(channel, event) -> str:
	code = start_code(event.text) if event.text and not event.approval_id else None
	if code:
		return connect(channel, event, code)
	user = links.user_for_chat(event.sender)
	if user is None:
		return stranger(channel, event)
	return answer(channel, event, user)


def connect(channel, event, code: str) -> str:
	if not first_time(event):
		return "duplicate"
	done = links.redeem(code, event.sender)
	channel.send_text(event.sender, done.sentence)
	if done.left:
		channel.send_text(
			done.left,
			_(
				"AI Munimji is now connected to another Telegram chat of yours, so this chat no longer gets requests."
			),
		)
	return "linked" if done.user else "refused_link"


def stranger(channel, event) -> str:
	"""Nobody is connected to this chat. A press is refused; a message gets the chat's own id, once in a while (the engine's channel keeps that count)."""
	if event.approval_id:
		channel.acknowledge(event, "You are not registered to answer these requests.")
	else:
		channel.handle_command(event, known=False)
	return "stranger"


def answer(channel, event, user: str) -> str:
	if not first_time(event):
		return "duplicate"
	with as_user(user):
		services = wiring.person_services(telegram=True, for_desk=False)
		approvals = services.approvals
		approvals.inbound = (
			None  # the update was claimed above, in the system mode: a person has no right to the ledger
		)
		router = approvals.router
		conversation = TypedConversation(
			approvals,
			router,
			memory=memory.CacheConversationMemory(),
			clock=time.time,
			not_understood=NOT_UNDERSTOOD,
		)
		result = process_inbound(event, router, approvals, conversation)
		tell_what_happens_next(channel, event, result, services)
	return "handled"


def tell_what_happens_next(channel, event, result, services) -> None:
	"""After an answer that was recorded, the one plain sentence the Desk shows too (next_step.py): what happens next. The engine's own words (Recorded: ...) have been sent already."""
	if result is None or not result.ok or result.status != "decided" or result.approval is None:
		return
	try:
		said = next_step.after_answer(result.approval, services)
	except Exception:  # the answer is given and kept: a sentence that cannot be worked out must not undo it
		frappe.logger("ai_munimji").warning(
			"the sentence after a Telegram answer could not be made", exc_info=True
		)
		return
	if said is not None:
		channel.send_text(event.sender, said.text)
