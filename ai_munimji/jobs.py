import frappe
from frappe.utils import now_datetime

LOG = "ai_munimji"


def check_stock() -> int:
	"""Scheduled job: ask for a purchase wherever a warehouse holds less than the threshold. Rules decide; a person answers.

	Reads ERPNext's Bin table in process (no API key, no HTTP). It creates a Pending request and nothing else, and not a second one
	while a request for the same item and warehouse is still Pending. Returns how many it created.
	"""
	settings = frappe.get_cached_doc("AI Munimji Settings")
	if not settings.enabled:
		return 0

	threshold = settings.stock_threshold or 0
	low = frappe.get_all(
		"Bin",
		filters={"actual_qty": ["<", threshold]},
		fields=["item_code", "warehouse", "actual_qty"],
		order_by="item_code, warehouse",
	)

	created = 0
	for row in low:
		if frappe.db.exists(
			"Munimji Approval Request", {"item_code": row.item_code, "warehouse": row.warehouse, "status": "Pending"}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Munimji Approval Request",
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"qty": max(2 * threshold - row.actual_qty, 1),
				"supplier": _supplier_for(row.item_code) or settings.fallback_supplier,
				"reason": f"{row.actual_qty:g} on hand in this warehouse, below {threshold:g}; the request is for enough to reach {2 * threshold:g}.",
			}
		).insert()
		created += 1

	frappe.logger(LOG).info(f"check_stock ran as {frappe.session.user}: {len(low)} below the threshold, {created} request(s) created")
	return created


def _supplier_for(item_code: str) -> str | None:
	return frappe.db.get_value("Item Default", {"parent": item_code}, "default_supplier")


def tick_probe() -> None:
	"""Measurement only (added to the hooks for one experiment, then removed): writes the time it ran, to see how often the scheduler really calls a per-minute cron job."""
	frappe.logger(LOG).info(f"tick_probe {now_datetime().isoformat(timespec='seconds')} user={frappe.session.user}")
