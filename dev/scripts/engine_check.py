# Throw-away check (Phase 2, step 7; spike branch only, not for main): the engine's stock analysis and vendor scoring run INSIDE the bench, on the spike's own stock data.
#
#   .\dev\up.ps1                                   (starts the containers if they are stopped)
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh /workspace/ai_munimji/dev/wheels/<the wheel>
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/engine_check.py
#
# The wheel is built in the erpnext-ai-agents repository (python tools/check_engine_wheel.py --keep-wheel <folder>). The script reads Item, Bin, Stock Ledger Entry and Purchase Order
# Item as Administrator (a script, not a signed-in user: get_all is the allowed call here), turns them into the engine's types, and prints what the engine says. It changes nothing.
# What is data and what is an assumption is said on every line: the site has no consumption history, so one run uses an ASSUMED use of 1 a day to show the cover arithmetic, and the
# vendor comparison adds a WHAT-IF second vendor, because the site has one supplier.
from collections import defaultdict
from datetime import timedelta

import ai_munimji_engine
from ai_munimji_engine.packs.stock_procurement.erp import DailyUsage, ItemInfo, StockInfo, VendorOffer, WarehouseStock
from ai_munimji_engine.packs.stock_procurement.inventory.analysis import analyze_item
from ai_munimji_engine.packs.stock_procurement.procurement.scoring import Need, rank_vendors
from ai_munimji_engine.packs.stock_procurement.settings import Policy, ProcurementSettings

results = []


def check(label, ok, detail=""):
	results.append(bool(ok))
	print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" ({detail})" if detail else ""))


print(f"engine {ai_munimji_engine.__version__} imported from {ai_munimji_engine.__file__}")
check("the engine comes from the bench's own Python environment, not from a repository checkout", "/env/" in ai_munimji_engine.__file__.replace("\\", "/"))

today = frappe.utils.getdate()
items = frappe.get_all("Item", filters={"item_code": ["like", "MD-%"]}, fields=["item_code", "item_name", "item_group", "stock_uom", "standard_rate"], order_by="item_code")
check("the spike's items are on the site", len(items) >= 3, ", ".join(i.item_code for i in items))

bins = defaultdict(list)
for b in frappe.get_all(
	"Bin",
	filters={"item_code": ["in", [i.item_code for i in items]]},
	fields=["item_code", "warehouse", "actual_qty", "reserved_qty", "ordered_qty", "planned_qty", "indented_qty", "reserved_qty_for_production",
	        "reserved_qty_for_sub_contract", "reserved_qty_for_production_plan", "projected_qty"],
):
	bins[b.item_code].append(b)


def stock_of(code):
	rows = bins.get(code, [])
	total = lambda field: float(sum((r.get(field) or 0) for r in rows))  # noqa: E731
	return StockInfo(
		on_hand=total("actual_qty"), reserved=total("reserved_qty"), incoming=total("ordered_qty"), planned=total("planned_qty"),
		reserved_production=total("reserved_qty_for_production"), reserved_subcontract=total("reserved_qty_for_sub_contract"),
		reserved_production_plan=total("reserved_qty_for_production_plan"), requested=total("indented_qty"), projected=total("projected_qty"),
		by_warehouse=tuple(WarehouseStock(r.warehouse, float(r.actual_qty or 0), float(r.reserved_qty or 0), float(r.ordered_qty or 0)) for r in rows),
	)


def usage_of(code):
	per_day = defaultdict(float)
	for e in frappe.get_all("Stock Ledger Entry", filters={"item_code": code, "actual_qty": ["<", 0], "is_cancelled": 0}, fields=["posting_date", "actual_qty"]):
		per_day[frappe.utils.getdate(e.posting_date)] += -float(e.actual_qty)
	return [DailyUsage(day, qty) for day, qty in sorted(per_day.items())]


policy = Policy(min_days_cover=7)
analyses = {}
print("\nstock analysis, on the site's Bin rows")
for it in items:
	info = ItemInfo(code=it.item_code, name=it.item_name, group=it.item_group, uom=it.stock_uom)
	stock, usage = stock_of(it.item_code), usage_of(it.item_code)
	real = analyze_item(info, stock, usage, policy, today)
	assumed_usage = [DailyUsage(today - timedelta(days=n), 1.0) for n in range(1, 31)]
	what_if = analyze_item(info, stock, assumed_usage, policy, today)
	analyses[it.item_code] = what_if
	print(f"  {it.item_code:14} on hand {real.on_hand:g} {it.stock_uom} (Bin), {len(usage)} days of use on record -> {real.status} / {real.confidence}")
	print(f"  {'':14} ASSUMED 1 a day for 30 days -> {what_if.status}, cover {what_if.cover_days_on_hand if what_if.cover_days_on_hand is None else round(what_if.cover_days_on_hand, 1)} days, "
	      f"suggested order {what_if.suggested_qty}; first reason: {what_if.reasons[0].text if what_if.reasons else '-'}")
check("every item got an analysis with a status", len(analyses) == len(items) and all(a.status for a in analyses.values()))
bolt, nut = analyses["MD-BOLT-M8"], analyses["MD-NUT-M8"]
check("the stock the engine saw is the stock on the site", bolt.on_hand == sum(b.actual_qty for b in bins["MD-BOLT-M8"]) and nut.on_hand == sum(b.actual_qty for b in bins["MD-NUT-M8"]),
      f"{bolt.on_hand:g} and {nut.on_hand:g}")
check("with the same assumed use the item with less stock has less cover, and is not called fine", bolt.on_hand < nut.on_hand and bolt.cover_days_on_hand < nut.cover_days_on_hand and bolt.kind != "OK",
      f"{bolt.cover_days_on_hand:g} days against {nut.cover_days_on_hand:g}; {bolt.kind}")

print("\nvendor scoring for MD-BOLT-M8")
code = "MD-BOLT-M8"
item = next(i for i in items if i.item_code == code)
supplier = frappe.db.get_value("Item Default", {"parent": code}, "default_supplier")
last = frappe.get_all("Purchase Order Item", filters={"item_code": code, "docstatus": ["<", 2]}, fields=["rate", "creation"], order_by="creation desc")
price = float(last[0].rate) if last else float(item.standard_rate or 0)
real_offer = VendorOffer(supplier=supplier, name=frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier, unit_price=price, orders=len(last),
                         last_order=frappe.utils.getdate(last[0].creation) if last else None, listed=True)
what_if_offer = VendorOffer(supplier="WHAT-IF", name="A second vendor (what-if: not on the site)", unit_price=round(price * 0.95, 2), lead_time_days=10.0, on_time_rate=0.8, orders=3,
                            payment_days=30.0)
a = analyses[code]
need = Need(qty=a.suggested_qty or 20.0, cover_days=a.cover_days_on_hand, fallback_lead_days=a.lead_time_days, uom=item.stock_uom)
ranking = rank_vendors([real_offer, what_if_offer], need, ProcurementSettings())
for v in ranking.vendors:
	print(f"  {'*' if v is ranking.best else ' '} {v.name:46} score {v.score:5.1f}  price {v.unit_price}  total {v.total}  lead {v.lead_days}  {('why not: ' + v.why_not) if v.why_not else 'recommended'}")
check("the site's own supplier and price went in as read from the site", real_offer.supplier == "Munimji Demo Supplier" and real_offer.unit_price > 0, f"{real_offer.name} at {real_offer.unit_price} ({real_offer.orders} order lines)")
check("both vendors were scored and one is recommended", len(ranking.eligible) == 2 and ranking.best is not None)
check("the vendor that is not recommended has a reason in words", all(v.why_not for v in ranking.vendors if v is not ranking.best))

print("\n" + ("all checks passed" if all(results) else "SOME CHECKS FAILED") + f" ({sum(results)} of {len(results)})")
if not all(results):
	raise SystemExit(1)
