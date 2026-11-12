# Seeds the DEVELOPMENT site with a small supply chain to follow the whole flow of a request in the browser, from the real stock check to the draft Purchase Order (dev/demo.ps1 runs it and
# prints the walkthrough). It adds, and changes nothing that exists:
#
#   MD-SCREW-M6   bought from THREE suppliers with different prices and delivery times, one of them late, with 90 days of usage; 40 on hand, about five days of stock: a reorder is due now.
#                   Quick Fasteners Ltd        4.50 each, delivers in about 4 days, as promised (5)
#                   Bharat Bolt Traders        4.10 each (the cheapest), promises 5 days and delivers in 9 to 12: LATE every time
#                   Munimji Demo Supplier      5.30 each (the dearest), delivers in 2 to 3 days, as promised (3)
#   MD-GASKET-G1  90 days of usage and 8 on hand, but no supplier and no purchase history: no comparison is possible, and the request says so.
#
# The suppliers are the three the development site already has (dev/scripts/seed.py and the demo orders on it); the items are new. Documents are made through the engine's own loader
# (ai_munimji_engine.testkit.loader), in process, with the dates of the past that the history needs (stock entries, delivery notes, purchase orders and their receipts). Each carries a
# marker (TD/MD-...), so running it again finds what is there and adds the rest. Dates are relative to today.
# An item that has been through the flow is "ordered recently" and is not asked about again, so the walkthrough can be repeated on a second pair of items: give a suffix, for example -B, and the
# items are MD-SCREW-M6-B and MD-GASKET-G1-B (the same suppliers).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_demo_flow.py [suffix]
import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(os.environ.get("MUNIMJI_REPO", "/workspace/ai_munimji"))
sys.path.insert(0, str(REPO / "dev" / "scripts"))
from ai_munimji_engine.testkit import loader as loader_module
from ai_munimji_engine.testkit.world import Item, Move, Order, Sale, Supplier, Warehouse, World
from inprocess_writer import InProcessWriter

assert frappe.local.site.startswith("development"), (
	f"{frappe.local.site} is not the development site: this script posts about 200 documents"
)
TODAY = date.today()
QUICK, BHARAT, DEMO = "Quick Fasteners Ltd", "Bharat Bolt Traders", "Munimji Demo Supplier"
SUFFIX = args[0] if args else ""  # `args` is given by dev/frappe_run.py
SCREW, GASKET = f"MD-SCREW-M6{SUFFIX}", f"MD-GASKET-G1{SUFFIX}"
ON_HAND = {"screw": 40, "gasket": 8}
LEFT_BY = 2  # the item's usage stops this many days ago: the last delivery is not today's


def usage(item: str) -> list[Sale]:
	"""90 days of deliveries to customers, none on a Sunday. The screw is used faster in the last two weeks; the gasket steadily."""
	sales = []
	for d in range(LEFT_BY, 91):
		if (TODAY - timedelta(days=d)).weekday() == 6:
			continue
		qty = (8 + d % 3 if d <= 14 else 5 + d % 3) if item == "screw" else 2 + d % 2
		sales.append(Sale(item, "stores", qty, d))
	return sales


def orders() -> list[Order]:
	"""Nine past orders of the screw, three from each supplier, 25 each. received_after is the days from the order to the goods; due_in is what the supplier promised."""
	plan = (
		("quick", 4.50, 5, (80, 55, 30), (4, 5, 4)),
		("bharat", 4.10, 5, (75, 50, 25), (11, 9, 12)),
		("demo", 5.30, 3, (70, 45, 20), (2, 2, 3)),
	)
	return [
		Order(f"{who}{n}", who, "screw", "stores", 25, rate, ago, due, received)
		for who, rate, due, agos, received_in in plan
		for n, (ago, received) in enumerate(zip(agos, received_in, strict=True), 1)
	]


def build() -> World:
	sales = usage("screw") + usage("gasket")
	past_orders = orders()
	moves = []
	for item in ("screw", "gasket"):
		used = sum(s.qty for s in sales if s.item == item)
		received = sum(o.qty for o in past_orders if o.item == item)
		moves.append(
			Move(item, "stores", used + ON_HAND[item] - received, 95, rate=4.5)
		)  # what makes the shelf hold ON_HAND today
	return World(
		warehouses=(Warehouse("stores"),),
		items=(
			Item(
				"screw",
				f"Screw M6 x 20{' (' + SUFFIX.strip('-') + ')' if SUFFIX else ''}",
				lead_time_days=7,
				suppliers=("quick", "bharat", "demo"),
			),
			Item(
				"gasket",
				f"Gasket G1 (no supplier yet){' (' + SUFFIX.strip('-') + ')' if SUFFIX else ''}",
				lead_time_days=7,
			),
		),
		suppliers=(Supplier("quick", QUICK), Supplier("bharat", BHARAT), Supplier("demo", DEMO)),
		moves=tuple(moves),
		sales=tuple(sales),
		orders=tuple(past_orders),
		quotes=(),
		sales_orders=(),
		tax_rules=(),
	)


class DemoLoader(loader_module.Loader):
	def _names(self) -> dict[str, str]:
		names = {"stores": f"Stores - {self.abbr}", "screw": SCREW, "gasket": GASKET}
		names.update({s.key: s.name for s in self.world.suppliers})
		return names


world = build()
problems = world.problems()
assert not problems, f"the demo world is not one an ERP can hold: {problems}"
loader_module.MARK = f"TD/MD{SUFFIX}-"
loader_module.ITEM_GROUP, loader_module.CUSTOMER_GROUP = "Demo Goods", "Demo Customers"
loader_module.TERRITORY, loader_module.CUSTOMER = "Demo Territory", "Demo Customer"
writer = InProcessWriter()
site = DemoLoader(writer, world, TODAY).run()
frappe.db.commit()
print("Made:\n" + writer.summary())

# what the engine will see, read the way the vendor comparison reads it
from ai_munimji.erp_client import FrappeERPClient

erp = FrappeERPClient(system=True)
since = TODAY - timedelta(days=480)
for code in (SCREW, GASKET):
	stock = erp.get_stock([code])[code]
	used = sum(u.qty for u in erp.get_consumption([code], TODAY - timedelta(days=90), TODAY)[code])
	print(f"{code}: {stock.on_hand:g} on hand, {used:g} used in the last 90 days")
	for o in erp.get_vendor_offers(code, since):
		print(
			f"   {o.name}: {o.unit_price:.2f} each, delivers in {o.lead_time_days:g} days, on time {o.on_time_rate:.0%} of {o.orders} orders"
		)
	if not erp.get_vendor_offers(code, since):
		print("   no supplier and no purchase history: no comparison is possible")
