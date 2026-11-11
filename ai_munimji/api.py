import json

import frappe
from frappe import _

from ai_munimji import flow as flow_block
from ai_munimji import jobs, markup, next_step, wiring

# What the engine says when an answer lost to another one given at the same moment ("pending": the request was read before the other answer was kept) or could not be applied
# ("error": the engine puts the database's own words in the message). A person is not shown those words.
NOT_APPLIED = ("error", "pending")
MAX_PARAMS_CHARS = 2000  # the longest answer a button sends is a few dozen characters ({"qty": 150}, {"supplier": "SUP-0001"})


def read_params(params) -> dict | None:
	"""The answer's parameters as a button sends them: a JSON object as text, or nothing. Returns the object, or None when nothing was sent. Raises ValueError when what came is not an
	object (not JSON, a list, a number, a string, null) or is far longer than any button sends: the caller refuses the answer, with a plain sentence."""
	if params is None or params == "":
		return None
	if len(params) > MAX_PARAMS_CHARS:
		raise ValueError("too long")
	try:
		value = json.loads(params)
	except (TypeError, ValueError, RecursionError):
		raise ValueError("not JSON") from None
	if not isinstance(value, dict):
		raise ValueError("not an object")
	return value


def busy(approval_id: str, action: str, detail: str) -> dict:
	"""The one sentence a person reads when their answer was not applied because of another one at the same moment. The detail (the database's words) goes to the log, not to the screen."""
	frappe.logger("ai_munimji").warning(f"answer {action} to {approval_id} was not applied: {detail}")
	return {
		"ok": False,
		"status": "busy",
		"message": _(
			"Someone else is answering this request at the same moment, or your answer could not be applied just now. Nothing was changed. Reload the page and look at the request: if it was answered you will see who answered first, and if it is still waiting you can answer it again."
		),
	}


@frappe.whitelist(methods=["POST"])
def answer(approval_id: str, action: str, params: str | None = None) -> dict:
	"""A person answers a request. The engine decides what the answer does (a reorder becomes a work order, an order is made as a draft in ERPNext in this person's name, a second answer
	is refused with who answered first); this only carries the answer in as the signed-in person. The request form's buttons call it: approve, dismiss, change_qty (params: qty) and
	change_vendor (params: supplier; without it the answer lists the vendors to choose from).

	`approval` is the request to look at next: after a change the engine replaces the request with a revised one and closes this one. When an answer lost to another one given at the same
	moment, or could not be applied, the status is "busy" and the message is one plain sentence (`busy()`), never the database's words. Parameters that are not a JSON object are refused
	(status "refused") before anything is looked at."""
	frappe.has_permission(
		wiring.REQUEST, "read", throw=True
	)  # whoever may not even look at requests is refused here; what a person may answer is the engine's to decide, from their rights
	try:
		given = read_params(params)
	except ValueError:
		return {
			"ok": False,
			"status": "refused",
			"message": _(
				"This answer could not be read, so nothing was done. Reload the page and press the button again."
			),
		}
	services = wiring.person_services()
	try:
		result = services.approvals.decide(approval_id, action, wiring.actor_for(), "desk", given)
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError) as exc:
		frappe.db.rollback()
		return busy(approval_id, action, f"{type(exc).__name__}: {exc}")
	if not result.ok and result.status in NOT_APPLIED:
		return busy(approval_id, action, f"{result.status}: {result.message}")
	out = {"ok": result.ok, "status": result.status, "message": result.message}
	if result.ok and result.status == "decided" and result.approval is not None:
		try:
			said = next_step.after_answer(result.approval, services)
		except Exception:  # the answer is given and kept: a sentence that cannot be worked out must not turn it into an error
			frappe.logger("ai_munimji").warning(
				f"the sentence after answer {action} to {approval_id} could not be made", exc_info=True
			)
			said = None
		if (
			said is not None
		):  # what happens next, in one plain sentence; the engine's own words stand for the kinds of request it does not cover
			out["message"], out["message_html"] = said.text, said.html
			if said.document:
				out["document"] = {
					"doctype": said.document[0],
					"name": said.document[1],
					"path": markup.form_path(*said.document),
				}
	if result.approval is not None:
		out["approval"] = result.approval.id
	if result.choices:
		out["choices"] = result.choices
	if result.prompt:
		out["prompt"] = result.prompt
	return out


@frappe.whitelist(methods=["GET", "POST"])
def flow(approval_id: str) -> dict:
	"""The Flow block of a request (flow.py): reorder request -> purchase request -> Draft Purchase Order, each step a link, the request on the screen marked. Returns {"html", "refresh_in"}:
	"html" is already escaped, and "refresh_in" is the seconds after which the form asks again (not 0 while the purchase request is being made). Read as the signed-in person: whoever may
	not read the request gets a refusal, and a request in the chain that they may not read is not shown."""
	frappe.has_permission(wiring.REQUEST, "read", doc=approval_id, throw=True)
	return flow_block.flow_for(approval_id)


MANAGERS = ("Munimji Manager", "System Manager")


@frappe.whitelist(methods=["POST"])
def run_check_now() -> dict:
	"""The Run the check now button of the Settings page: queues the stock check at once instead of waiting for the time set on the page. Only a Munimji Manager or a System Manager may press
	it. It refuses, in a plain sentence, while a check is waiting in the queue or running (two checks at once would read the whole stock twice), and while Watch stock is off. Returns
	{"ok", "status", "message"} and the page's status block (`check_status`)."""
	frappe.only_for(MANAGERS)
	outcome = jobs.queue_stock_check()
	messages = {
		"queued": _(
			"The stock check is queued and starts in a moment. This page shows how far it has got; the requests it makes appear in Munimji Approval Request."
		),
		"queued_already": _(
			"A stock check is already waiting to start. Nothing more was queued: wait for it to finish."
		),
		"running": _(
			"A stock check is running now. Nothing more was queued: wait for it to finish, then press the button again if you need another."
		),
		"off": _("Watch stock is switched off, so no check can run. Switch it on and save the page first."),
	}
	return {
		"ok": outcome == "queued",
		"status": outcome,
		"message": messages[outcome],
		**jobs.check_status(),
	}


@frappe.whitelist(methods=["GET", "POST"])
def check_status() -> dict:
	"""When the last stock check ran, how far it got and how many requests it made, and whether one is queued or running now (jobs.check_status). For the people who may open the Settings page."""
	frappe.has_permission("AI Munimji Settings", "read", throw=True)
	return jobs.check_status()
