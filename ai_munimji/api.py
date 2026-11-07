import json

import frappe

from ai_munimji import wiring


@frappe.whitelist(methods=["POST"])
def answer(approval_id: str, action: str, params: str | None = None) -> dict:
	"""A person answers a request. The engine decides what the answer does (a reorder becomes a work order, an order is made as a draft in ERPNext in this person's name, a second answer
	is refused); this only carries the answer in as the signed-in person. The screens that call it are Phase 5's; the request form has one button for a purchase until then."""
	frappe.has_permission(
		wiring.REQUEST, "read", throw=True
	)  # whoever may not even look at requests is refused here; what a person may answer is the engine's to decide, from their rights
	services = wiring.person_services()
	result = services.approvals.decide(
		approval_id, action, wiring.actor_for(), "desk", json.loads(params) if params else None
	)
	return {"ok": result.ok, "status": result.status, "message": result.message}
