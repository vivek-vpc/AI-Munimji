"""The Flow block on a request: where this request stands between the three steps a person follows (Group 2, F3 of the production-readiness review).

    Reorder request  ->  Purchase request  ->  Draft Purchase Order

A reorder request is what the stock check raises for an item that is running low. When a person approves it, the vendors are compared and a purchase request is made, with the recommended vendor
and why the others were not chosen. When a person approves that, ERPNext gets a Draft Purchase Order. Each step is a link; the one the request on the screen belongs to is marked; a request that
was changed shows what replaced it. A reorder that was approved and has no purchase request yet says so, and the form asks for the block again every few seconds until it appears.

The block is written here, on the server, as HTML, and every piece of text that is not a word of ours (the titles of the requests, the vendor's name, the order's number, the engine's own
sentences) goes through `markup.esc`. The Desk form only puts the result on the page. It is read as the signed-in person: a record they may not read is not shown.
"""

import json
from dataclasses import dataclass, field

import frappe
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND as REORDER
from ai_munimji_engine.packs.stock_procurement.procurement.messages import (
	KIND_MANUAL,
	KIND_ORDER,
	KIND_PO,
	KIND_PR,
)
from frappe import _

from ai_munimji import markup, schedule
from ai_munimji.stores import convert, frappe_core_stores, frappe_stock_stores

REQUESTS = "Munimji Approval Request"
PURCHASE_KINDS = (KIND_PO, KIND_PR, KIND_MANUAL)
POLL_SECONDS = 5  # how often the form asks again while the purchase request is being made


@dataclass
class Chain:
	"""The records of one flow, as the stores' rows. Any of them may be missing: a purchase asked for directly has no reorder request, and a reorder that is not approved has nothing after it."""

	viewed: dict
	reorder: dict | None = None
	work_order: dict | None = None
	proposal: dict | None = None
	purchase: dict | None = None  # the purchase request the second step shows
	earlier: list[dict] = field(default_factory=list)  # the purchase requests this one replaced


@dataclass
class Step:
	number: int
	title: str
	state: str  # "done", "waiting", "stopped" or "later"
	status: str  # the word in the step's pill
	here: bool = False
	links: list[tuple[str, str]] = field(default_factory=list)  # (label, path)
	lines: list[str] = field(default_factory=list)  # plain text, escaped when it is written
	notes: list[str] = field(
		default_factory=list
	)  # a sentence that holds markup of ours already escaped (a link inside it)
	being_made: bool = False  # the purchase request is being made: the form asks again in a few seconds


def _json(text) -> dict:
	try:
		value = json.loads(text) if text else {}
	except ValueError:
		return {}
	return value if isinstance(value, dict) else {}


def _title(row: dict) -> str:
	return str(_json(row["request_json"]).get("title") or row["id"])


def _decision(row: dict) -> dict:
	return _json(row["decision_json"])


def _when(text) -> str:
	moment = convert.to_datetime(text)
	return frappe.utils.format_datetime(moment, "d MMM, HH:mm") if moment else ""


def _approved(row: dict | None) -> bool:
	return bool(
		row and row["status"] == "decided" and _decision(row).get("action") in ("approve", "requisition")
	)


def _seen(lookup, *args):
	"""A record of the chain, or None when there is none or this person may not read it: a flow shows what the person can see, and a step whose record is hidden reads as one that is not there."""
	try:
		return lookup(*args)
	except frappe.PermissionError:
		return None


def follow(row: dict, core, stock) -> Chain | None:
	"""The records around this request, or None for a kind of request that is not part of this flow (a notice, the monitor's warning)."""
	kind = row["kind"]
	if kind == REORDER:
		chain = Chain(viewed=row, reorder=row)
		if not _approved(row) or not row.get("ref_id"):
			return chain
		orders = _seen(core.workorders.with_source, f"inventory_alert:{row['ref_id']}") or []
		if len(orders) > 1:  # the alert was asked about more than once: take the one this request made
			orders = [o for o in orders if _json(o["payload_json"]).get("approval_id") == row["id"]]
		chain.work_order = orders[0] if orders else None
		if chain.work_order:
			chain.proposal = _seen(stock.proposals.for_work_order, chain.work_order["id"])
		if chain.proposal and chain.proposal["approval_id"]:
			chain.purchase = _seen(core.approvals.get, chain.proposal["approval_id"])
		return chain
	if kind not in PURCHASE_KINDS and kind != KIND_ORDER:
		return None
	chain = Chain(viewed=row)
	if row.get("ref_type") == "procurement_proposal" and row.get("ref_id"):
		chain.proposal = _seen(stock.proposals.get, row["ref_id"])
	if chain.proposal is None:
		return chain
	chain.work_order = _seen(core.workorders.get, chain.proposal["work_order_id"])
	reorder_id = _json(chain.work_order["payload_json"]).get("approval_id") if chain.work_order else None
	chain.reorder = _seen(core.approvals.get, reorder_id) if reorder_id else None
	current = chain.proposal["approval_id"]
	if kind in PURCHASE_KINDS:
		chain.purchase = row
		if current == row["id"]:  # the request that stands now: the ones it replaced, oldest first
			chain.earlier = [
				r
				for r in _seen(
					core.approvals.with_reference, "procurement_proposal", row["ref_id"], row["id"]
				)
				or []
				if r["kind"] in (KIND_PO, KIND_PR) and r["status"] == "cancelled"
			]
	else:
		chain.purchase = _seen(core.approvals.get, current) if current else None
	return chain


def _outcome(row: dict) -> tuple[str, str, str]:
	"""(the word in the pill, the state, one sentence) for a request, from how it ended."""
	status, decision = row["status"], _decision(row)
	if status == "pending":
		return _("Waiting for an answer"), "waiting", ""
	if status == "decided":
		who, when = decision.get("actor_id") or "?", _when(row.get("decided_at"))
		action = decision.get("action")
		if action in ("approve", "requisition"):
			return _("Approved"), "done", _("Approved by {0}, {1}.").format(who, when)
		if action == "dismiss":
			return (
				_("Dismissed"),
				"stopped",
				_("Dismissed by {0}, {1}. Nothing was ordered.").format(who, when),
			)
		if action == "snooze":
			return _("Snoozed"), "stopped", _("Snoozed by {0}, {1}. Nothing was ordered.").format(who, when)
		return _("Answered"), "done", _("Answered by {0}, {1}.").format(who, when)
	if status == "expired":
		return _("Expired"), "stopped", _("Nobody answered in time. Nothing was ordered.")
	return _("Closed"), "stopped", row.get("status_note") or ""


def _reorder_step(chain: Chain) -> Step:
	row = chain.reorder
	if row is None:
		return Step(
			1,
			_("Reorder request"),
			"done",
			_("Not needed"),
			lines=[_("This purchase was asked for directly, so there was no reorder request.")],
		)
	pill, state, line = _outcome(row)
	return Step(
		1,
		_("Reorder request"),
		state,
		pill,
		links=[(_title(row), markup.form_path(REQUESTS, row["id"]))],
		lines=[line] if line else [],
	)


def _problem_of(row: dict) -> str:
	"""The reason the engine gave for being unable to compare vendors (the first line of its "What is needed" section)."""
	for section in _json(row["request_json"]).get("sections") or []:
		if section.get("heading") == "What is needed" and section.get("lines"):
			return str(section["lines"][0])
	return ""


def _purchase_step(chain: Chain) -> Step:
	title = _("Purchase request")
	row, reorder = chain.purchase, chain.reorder
	if row is None:
		if reorder is not None and _approved(reorder):
			if chain.work_order is None or chain.work_order["status"] == "pending" or chain.proposal is None:
				when = schedule.next_check()
				return Step(
					2,
					title,
					"waiting",
					_("Being made"),
					being_made=True,
					lines=[
						_(
							"The vendors are being compared. The purchase request appears here in about a minute."
						),
						_("If it does not, the next scheduled check ({0}) makes it.").format(
							frappe.utils.format_datetime(when, "d MMM, HH:mm")
							if when
							else _("the time set in AI Munimji Settings")
						),
					],
				)
			return Step(
				2,
				title,
				"stopped",
				_("Not found"),
				lines=[_("No purchase request was found for this reorder.")],
			)
		if reorder is not None and reorder["status"] == "pending":
			return Step(2, title, "later", _("Not yet"), lines=[_("Made after the reorder is approved.")])
		if reorder is not None:
			return Step(
				2,
				title,
				"stopped",
				_("Not made"),
				lines=[_("The reorder was not approved, so the vendors were not compared.")],
			)
		return Step(2, title, "later", _("Not yet"))

	pill, state, line = _outcome(row)
	step = Step(2, title, state, pill, links=[(_title(row), markup.form_path(REQUESTS, row["id"]))])
	if line:
		step.lines.append(line)
	proposal = chain.proposal or {}
	replaced_by = proposal.get("approval_id")
	if row["status"] == "cancelled" and replaced_by and replaced_by != row["id"]:
		step.status, step.state = _("Changed"), "done"
		step.lines = []
		step.notes.append(
			markup.esc(_("This request was changed. It was replaced by {0}.")).replace(
				"{0}", markup.link(markup.form_path(REQUESTS, replaced_by), _("the new request"))
			)
		)
	elif row["kind"] == KIND_MANUAL:
		step.lines.insert(0, _("No vendor could be compared for this item, so no purchase request was made."))
		reason = _problem_of(row)
		if reason:
			step.lines.insert(1, reason)
		if row["status"] == "pending":
			step.lines.append(
				_("What to do: order it in ERPNext by hand, then press “Got it” on that request.")
			)
	elif proposal.get("supplier_name") and row["status"] == "pending":
		step.lines.append(
			_("Recommended: {0}, {1} in total.").format(
				proposal["supplier_name"], f"{float(proposal.get('total') or 0):,.2f}"
			)
		)
	if chain.earlier:
		step.links.extend(
			(_("Earlier version, {0}").format(_when(r["created_at"])), markup.form_path(REQUESTS, r["id"]))
			for r in chain.earlier
		)
	return step


def _order_step(chain: Chain) -> Step:
	title = _("Draft Purchase Order")
	proposal, purchase = chain.proposal or {}, chain.purchase
	number = proposal.get("po_name")
	if number:
		requisition = _json(proposal.get("ranking_json")).get("document") == "requisition"
		doctype = "Material Request" if requisition else "Purchase Order"
		when = _when(purchase.get("decided_at")) if purchase else ""
		return Step(
			3,
			_("Draft purchase requisition") if requisition else title,
			"done",
			_("Made"),
			links=[(number, markup.form_path(doctype, number))],
			lines=[
				(
					_("Made as a draft, {0}. Your buyer turns it into an order in ERPNext.")
					if requisition
					else _(
						"Made as a draft, {0}. Review and submit it in ERPNext. Nothing has been sent to the vendor."
					)
				).format(when)
			],
		)
	if purchase is None:
		return Step(3, title, "later", _("Not yet"))
	if purchase["kind"] == KIND_MANUAL:
		return Step(
			3,
			title,
			"later" if purchase["status"] == "pending" else "stopped",
			_("Not made here"),
			lines=[_("It is ordered in ERPNext by hand.")],
		)
	if _approved(purchase):
		return Step(
			3,
			title,
			"stopped",
			_("Not made"),
			lines=[_("No order was made: creating orders is switched off in the procurement settings.")],
		)
	if purchase["status"] == "pending":
		return Step(3, title, "later", _("Not yet"), lines=[_("Made when the purchase request is approved.")])
	if purchase["status"] == "cancelled" and proposal.get("approval_id") != purchase["id"]:
		return Step(3, title, "later", _("Not yet"), lines=[_("Made when the new request is approved.")])
	return Step(3, title, "stopped", _("Not made"), lines=[_("Nothing was ordered.")])


def _here(chain: Chain) -> int:
	kind = chain.viewed["kind"]
	return 1 if kind == REORDER else (3 if kind == KIND_ORDER else 2)


PILL = {"done": "green", "waiting": "orange", "stopped": "gray", "later": "gray"}


def render(steps: list[Step]) -> str:
	"""The block as HTML. Everything that is text goes through markup.esc; the tags and the styles are ours."""
	cells = []
	for step in steps:
		border = "var(--primary)" if step.here else "var(--border-color)"
		weight = "2px" if step.here else "1px"
		marker = (
			f' <span class="indicator-pill blue">{markup.esc(_("You are here"))}</span>' if step.here else ""
		)
		body = [
			f'<div class="text-muted small">{markup.esc(_("Step {0} of 3").format(step.number))}</div>',
			f"<div><b>{markup.esc(step.title)}</b> "
			f'<span class="indicator-pill {PILL[step.state]}">{markup.esc(step.status)}</span>{marker}</div>',
		]
		body += [f"<div>{markup.link(path, label)}</div>" for label, path in step.links]
		body += [f'<div class="text-muted small">{markup.esc(line)}</div>' for line in step.lines]
		body += [f'<div class="text-muted small">{note}</div>' for note in step.notes]
		current = ' aria-current="step"' if step.here else ""
		cells.append(
			f'<div role="listitem"{current} style="flex: 1 1 14rem; min-width: 0; border: {weight} solid {border}; '
			f'border-radius: var(--border-radius-md); padding: var(--padding-md)">{"".join(body)}</div>'
		)
	arrow = '<div aria-hidden="true" class="text-muted" style="align-self: center">&rarr;</div>'
	label = markup.esc(_("The flow of this request: reorder request, purchase request, draft Purchase Order"))
	return (
		f'<div style="margin-bottom: var(--margin-lg)"><div class="text-muted small">{markup.esc(_("Flow"))}</div>'
		f'<div role="list" aria-label="{label}" style="display: flex; flex-wrap: wrap; gap: var(--margin-sm); '
		f'align-items: stretch">{arrow.join(cells)}</div></div>'
	)


def flow_for(approval_id: str) -> dict:
	"""The Flow block of this request as {"html": ..., "refresh_in": seconds}. An empty block ("html": "") for a request that is not part of the flow. "refresh_in" is not 0 while the
	purchase request is being made: the form asks again then."""
	core = frappe_core_stores()
	stock = frappe_stock_stores(core)
	row = core.approvals.get(approval_id)
	chain = follow(row, core, stock) if row else None
	if chain is None:
		return {"html": "", "refresh_in": 0}
	steps = [_reorder_step(chain), _purchase_step(chain), _order_step(chain)]
	steps[_here(chain) - 1].here = True
	return {
		"html": render(steps),
		"refresh_in": POLL_SECONDS if any(step.being_made for step in steps) else 0,
	}
