# Sets a SCALE site (never the development site) up for the load test of the production-readiness review (dev/loadtest.py): 100 approvers with API keys, a purchase history for 100 items so
# that each has a priced supplier, and 100 requests waiting for an answer (the "purchase request" of a reorder that has been approved: answering it makes a draft Purchase Order).
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_load.py [users=100]
# It writes the people and their keys to /tmp/load-users.json (inside the container), and the names of the requests to /tmp/load-requests.json. Run it again and it makes what is missing.
# Raw SQL for the purchase history: 100 submitted orders through the document API would also do, but this is only the history that the supplier comparison reads.
import json
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from frappe.core.doctype.user.user import generate_keys

from ai_munimji import jobs, wiring
from ai_munimji.tests.helpers import make_user

N = int(args[0]) if args else 100
SUPPLIER = "Munimji Demo Supplier"
COMPANY = "Munimji Demo Co"
WAREHOUSE = "Stores - MDC"
ROLES = ("Munimji Approver", "Purchase User", "Purchase Manager", "Stock User")
ITEMS = N + 10  # ten more requests than people: the same-request test needs one that the others do not use
CODES = [f"SC-{n:06d}" for n in range(1001, 1001 + ITEMS)]
db = frappe.db
start = time.time()

users = {}
frappe.flags.in_import = True  # Frappe refuses more than 60 new users a minute (throttle_user_creation) unless it is an import
for i in range(1, N + 1):
	email = f"load.approver.{i:03d}@example.com"
	if not db.exists("User", email):
		make_user(email, ROLES)
	secret = generate_keys(email)["api_secret"]
	users[email] = f"{db.get_value('User', email, 'api_key')}:{secret}"
frappe.flags.in_import = False
db.commit()
with open("/tmp/load-users.json", "w") as f:
	json.dump(users, f)
print(f"{N} approvers with keys: {time.time() - start:.0f} s", flush=True)

for n, code in enumerate(CODES, 1):
	order = f"LT-PO-{n:04d}"
	if db.exists("Purchase Order", order):
		continue
	db.sql(
		"""INSERT INTO `tabPurchase Order` (name, supplier, supplier_name, transaction_date, schedule_date, company, currency, conversion_rate, status, docstatus, creation, modified, modified_by, owner, idx)
		VALUES (%s, %s, %s, DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_SUB(CURDATE(), INTERVAL 20 DAY), %s, 'INR', 1, 'Completed', 1, NOW(6), NOW(6), 'Administrator', 'Administrator', 0)""",
		(order, SUPPLIER, SUPPLIER, COMPANY),
	)
	db.sql(
		"""INSERT INTO `tabPurchase Order Item` (name, parent, parenttype, parentfield, idx, item_code, item_name, qty, rate, base_rate, uom, stock_uom, conversion_factor, schedule_date, warehouse, docstatus, creation, modified, modified_by, owner)
		VALUES (%s, %s, 'Purchase Order', 'items', 1, %s, %s, 100, 5, 5, 'Nos', 'Nos', 1, DATE_SUB(CURDATE(), INTERVAL 20 DAY), %s, 1, NOW(6), NOW(6), 'Administrator', 'Administrator')""",
		(f"{order}-1", order, code, code, WAREHOUSE),
	)
db.sql("UPDATE `tabBin` SET actual_qty = 2, projected_qty = 2 WHERE item_code IN %s", (tuple(CODES),))
db.sql(
	"UPDATE `tabItem` SET disabled = IF(name IN %s, 0, disabled) WHERE name IN %s",
	(tuple(CODES), tuple(CODES)),
)
db.commit()
print(f"purchase history for {ITEMS} items: {time.time() - start:.0f} s", flush=True)

settings = frappe.get_doc("AI Munimji Settings")
settings.enabled, settings.min_qty, settings.min_days_cover, settings.stock_alerts = 1, 10, 0, 0
settings.save()
db.commit()

REQUEST = "Munimji Approval Request"
for table in (
	"Munimji Approval Request",
	"Munimji Stock Alert",
	"Munimji Work Order",
	"Munimji Purchase Proposal",
	"Munimji Stock Notice",
):
	db.delete(table)
db.commit()
# at most 20 new requests per run, worst first: run until every item has its reorder request
runs = 0
for _ in range(ITEMS // 20 + 3):
	jobs.run_stock_check(items=CODES)
	runs += 1
	db.commit()
	if db.count(REQUEST, {"item_code": ["in", CODES], "status": "pending"}) >= ITEMS:
		break
print(
	f"reorder requests: {db.count(REQUEST, {'status': 'pending'})} after {runs} runs: {time.time() - start:.0f} s",
	flush=True,
)

services = wiring.person_services()  # Administrator
actor = wiring.actor_for("Administrator")
for name in frappe.get_all(REQUEST, filters={"status": "pending", "kind": "inventory.reorder"}, pluck="name"):
	services.approvals.decide(name, "approve", actor, "desk")
	db.commit()
print(f"reorders approved: {time.time() - start:.0f} s", flush=True)
jobs.run_stock_check(items=CODES)  # the approved reorders become purchase requests
db.commit()
purchase = frappe.get_all(REQUEST, filters={"status": "pending", "kind": "procurement.po"}, pluck="name")
with open("/tmp/load-requests.json", "w") as f:
	json.dump(purchase, f)
print(f"{len(purchase)} purchase requests waiting: {time.time() - start:.0f} s")
