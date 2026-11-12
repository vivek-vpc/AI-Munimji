"""The one plain sentence a person reads after every answer: what happens next, and where to look (Group 2, F2 of the production-readiness review).

The engine's own words after an answer ("Recorded: Approve (by x via desk).") say that the answer was written down and nothing else; they do not say that the vendors are now being compared, where
the purchase request will appear, or what the number of the draft order is. This module turns an answered request into that sentence, for each kind of request and each answer, and gives the same
sentence with the order's number as a link to it (the Desk shows that one). Everything that comes from ERPNext (an order's number) is escaped (markup.py).

An answer that is not a plain answer (a refusal, a request that was answered before, a change that replaced the request with a revised one) keeps the engine's words: they already say what
happened. A kind of request this module does not know keeps them too.
"""

from dataclasses import dataclass

import frappe
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND as REORDER
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND_ALERT
from ai_munimji_engine.packs.stock_procurement.procurement.messages import KIND_MANUAL, KIND_PO, KIND_PR
from frappe import _

from ai_munimji import hand_off, markup, schedule
from ai_munimji.stores import locks

REQUESTS = "Munimji Approval Request"


@dataclass
class Said:
	text: str  # the sentence, as plain text
	html: str  # the same sentence, escaped, with the number of the draft as a link to it
	document: tuple[str, str] | None = None  # (doctype, name) of the draft this answer made, when it made one


def _plain(text: str) -> Said:
	return Said(text=text, html=markup.esc(text))


def next_check_text() -> str:
	"""When the scheduled check next starts, in words; the Settings page's setting when the time cannot be worked out."""
	when = schedule.next_check()
	return (
		frappe.utils.format_datetime(when, "d MMM, HH:mm")
		if when
		else _("the time set in AI Munimji Settings")
	)


def _snoozed(until) -> Said:
	if until is None:
		return _plain(_("Snoozed. You will be asked again later. Nothing was ordered."))
	return _plain(
		_("Snoozed. You will be asked again on {0}. Nothing was ordered.").format(
			frappe.utils.format_date(until)
		)
	)


def _reorder_approved(services) -> Said | None:
	"""A reorder was approved: the vendors are compared in the background, and the sentence says so, or says why they are not (and when they will be)."""
	handed = services.hand_off
	if handed is None or handed.outcome is None:
		return None  # no work order was made: the engine's words stand
	name = _("Munimji Approval Request")
	where = markup.link(markup.list_path(REQUESTS), name)
	if handed.outcome == hand_off.OFF:
		text = _(
			"Approved. Watch stock is switched off, so the vendors are not compared until you switch it on in AI Munimji Settings; the purchase request will appear in {0} after the next check."
		)
	elif handed.outcome == hand_off.QUEUED and not locks.held("stock_check"):
		text = _(
			"Approved. The vendors are being compared; the purchase request will appear in {0} in about a minute."
		)
	elif handed.outcome == hand_off.QUEUED:
		text = _(
			"Approved. A stock check is running just now, so the vendors may only be compared by the next scheduled check ({1}); the purchase request will then appear in {0}."
		)
	else:
		text = _(
			"Approved. The vendors will be compared by the next scheduled check ({1}); the purchase request will appear in {0} then."
		)
	when = next_check_text()
	return Said(
		text=text.format(name, when),
		html=markup.esc(text).replace("{0}", where).replace("{1}", markup.esc(when)),
	)


def _order_made(record, services) -> Said | None:
	"""A purchase request was approved: the draft order (or requisition) exists, and its number is the answer."""
	prop = services.proposals.by_approval(record.id)
	if prop is None or prop.status != "ordered":
		return None
	if not prop.po_name:
		return _plain(
			_(
				"Approved. No order was made in ERPNext: creating orders is switched off in the procurement settings."
			)
		)
	if (prop.ranking or {}).get("document") == "requisition":
		doctype, text = (
			"Material Request",
			_("Draft purchase requisition {0} made. Your buyer turns it into an order in ERPNext."),
		)
	else:
		doctype, text = "Purchase Order", _("Draft Purchase Order {0} made. Review and submit it in ERPNext.")
	path = markup.form_path(doctype, prop.po_name)
	return Said(
		text=text.format(prop.po_name),
		html=markup.esc(text).replace("{0}", markup.link(path, prop.po_name)),
		document=(doctype, prop.po_name),
	)


def after_answer(record, services) -> Said | None:
	"""What happens next, for the request `record` (as the engine holds it, already answered). None when the engine's own words should stand."""
	if record.status != "decided" or record.decision is None:
		return None
	action, kind = record.decision.action, record.kind
	if action == "dismiss" and kind in (REORDER, KIND_PO, KIND_PR):
		return _plain(_("Closed. Nothing was ordered."))
	if kind == REORDER:
		if action == "approve":
			return _reorder_approved(services)
		if action == "snooze":
			alert = services.alerts.by_approval(record.id)
			return _snoozed(alert.snoozed_until if alert else None)
	elif kind in (KIND_PO, KIND_PR):
		if action in ("approve", "requisition"):
			return _order_made(record, services)
		if action == "snooze":
			prop = services.proposals.by_approval(record.id)
			return _snoozed(prop.snoozed_until if prop else None)
	elif kind == KIND_MANUAL:
		if action == "ack":
			return _plain(
				_(
					"Marked as handled. Nothing was ordered from here: order it in ERPNext by hand if it is not ordered yet."
				)
			)
		if action == "snooze":
			prop = services.proposals.by_approval(record.id)
			return _snoozed(prop.snoozed_until if prop else None)
	elif kind == KIND_ALERT:
		if action == "ack":
			return _plain(_("Got it. This was for your information: nothing was ordered."))
		if action == "snooze":
			notice = services.inventory.notices.by_approval(record.id)
			return _snoozed(notice.snoozed_until if notice else None)
	return None
