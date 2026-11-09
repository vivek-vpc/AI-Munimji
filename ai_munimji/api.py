import json

import frappe
from frappe import _

from ai_munimji import wiring

# What the engine says when an answer lost to another one given at the same moment ("pending": the request was read before the other answer was kept) or could not be applied
# ("error": the engine puts the database's own words in the message). A person is not shown those words.
NOT_APPLIED = ("error", "pending")


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
	moment, or could not be applied, the status is "busy" and the message is one plain sentence (`busy()`), never the database's words."""
	frappe.has_permission(
		wiring.REQUEST, "read", throw=True
	)  # whoever may not even look at requests is refused here; what a person may answer is the engine's to decide, from their rights
	services = wiring.person_services()
	try:
		result = services.approvals.decide(
			approval_id, action, wiring.actor_for(), "desk", json.loads(params) if params else None
		)
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError) as exc:
		frappe.db.rollback()
		return busy(approval_id, action, f"{type(exc).__name__}: {exc}")
	if not result.ok and result.status in NOT_APPLIED:
		return busy(approval_id, action, f"{result.status}: {result.message}")
	out = {"ok": result.ok, "status": result.status, "message": result.message}
	if result.approval is not None:
		out["approval"] = result.approval.id
	if result.choices:
		out["choices"] = result.choices
	if result.prompt:
		out["prompt"] = result.prompt
	return out
