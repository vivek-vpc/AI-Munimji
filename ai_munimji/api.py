import json

import frappe

from ai_munimji import wiring


@frappe.whitelist(methods=["POST"])
def answer(approval_id: str, action: str, params: str | None = None) -> dict:
	"""A person answers a request. The engine decides what the answer does (a reorder becomes a work order, an order is made as a draft in ERPNext in this person's name, a second answer
	is refused with who answered first); this only carries the answer in as the signed-in person. The request form's buttons call it: approve, dismiss, change_qty (params: qty) and
	change_vendor (params: supplier; without it the answer lists the vendors to choose from).

	`approval` is the request to look at next: after a change the engine replaces the request with a revised one and closes this one."""
	frappe.has_permission(
		wiring.REQUEST, "read", throw=True
	)  # whoever may not even look at requests is refused here; what a person may answer is the engine's to decide, from their rights
	services = wiring.person_services()
	result = services.approvals.decide(
		approval_id, action, wiring.actor_for(), "desk", json.loads(params) if params else None
	)
	out = {"ok": result.ok, "status": result.status, "message": result.message}
	if result.approval is not None:
		out["approval"] = result.approval.id
	if result.choices:
		out["choices"] = result.choices
	if result.prompt:
		out["prompt"] = result.prompt
	return out
