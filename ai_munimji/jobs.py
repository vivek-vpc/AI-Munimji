import frappe

LOG = "ai_munimji"


def check_stock() -> int:
	"""PLACEHOLDER, replaced in Phase 5 by the engine's stock analysis. Scheduled job: ask for a purchase wherever a warehouse holds no more than the quantity in the settings.
	Rules decide; a person answers.

	Reads ERPNext's Bin table in process (no API key, no HTTP). It creates a Pending request and nothing else, and not a second one
	while a request for the same item and warehouse is still Pending. Returns how many it created. It uses only the first of the settings' rules, "at or below this quantity"
	(`min_qty`); 0 means that rule is not used, and then it asks for nothing.
	"""
	settings = frappe.get_cached_doc("AI Munimji Settings")
	if not settings.enabled:
		return 0

	threshold = settings.min_qty or 0
	if not threshold:
		return 0
	low = frappe.get_all(
		"Bin",
		filters={"actual_qty": ["<=", threshold]},
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
				"reason": f"{row.actual_qty:g} on hand in this warehouse, at or below {threshold:g}; the request is for enough to reach {2 * threshold:g}.",
			}
		).insert()
		created += 1

	# NB: Frappe's default log level is WARNING on a dev server and ERROR elsewhere, so this INFO line is written only if the level is raised
	frappe.logger(LOG).info(f"check_stock ran as {frappe.session.user}: {len(low)} at or below the quantity, {created} request(s) created")
	return created


def _supplier_for(item_code: str) -> str | None:
	return frappe.db.get_value("Item Default", {"parent": item_code}, "default_supplier")
