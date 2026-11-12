# Fills a SCALE site (never the development site) with a large stock: items, one Bin each, and a stock ledger of consumption and receipts, for the measurements of the production-readiness
# review (docs/SCALE_MEASUREMENTS.md): the stock check at 5,000 and at 30,000 items, and the ledger reads at about 5 million rows. It writes with bulk SQL, which is allowed here because this
# script is not part of the app (tests/test_rules.py reads only the app's package).
#
#   .\dev\exec.ps1 bash -c "cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh dev/scripts/seed.py"          # the company, a supplier, the demo users: once
#   .\dev\exec.ps1 bash -c "cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh dev/scripts/seed_scale.py 30000 167"
#
# The two numbers are the items and the ledger rows per item (30000 x 167 = 5.01 million). Run again with the same numbers and it adds nothing. About a twentieth of the items are
# nearly out of stock, another twentieth are running low, the rest have plenty.
import time

assert frappe.local.site.startswith("scale"), (
	f"{frappe.local.site} is not a scale site: this script writes millions of rows"
)
ITEMS = int(args[0]) if args else 30000
PER_ITEM = int(args[1]) if len(args) > 1 else 167
COMPANY, ABBR = "Munimji Demo Co", "MDC"
WAREHOUSE = f"Stores - {ABBR}"
CHUNK = 2000  # items per statement for the ledger: 2,000 x 167 = 334,000 rows, committed together
db = frappe.db
ALL_COLUMNS = "creation, modified, modified_by, owner, docstatus, idx"
STAMP = "NOW(6), NOW(6), 'Administrator', 'Administrator'"


def code(n: str) -> str:
	return f"CONCAT('SC-', LPAD({n}, 6, '0'))"


def timed(label, fn):
	start = time.time()
	fn()
	db.commit()
	print(f"{label}: {time.time() - start:.1f} s")


have = db.sql("SELECT COUNT(*) FROM `tabItem` WHERE name LIKE 'SC-%'")[0][0]
if have < ITEMS:
	timed(
		f"items {have + 1}..{ITEMS}",
		lambda: db.sql(
			f"""INSERT INTO `tabItem`
			(name, item_code, item_name, item_group, stock_uom, is_stock_item, disabled, lead_time_days, description, {ALL_COLUMNS})
			SELECT {code("seq")}, {code("seq")}, CONCAT('Scale item ', seq), 'All Item Groups', 'Nos', 1, 0, 7, CONCAT('Scale item ', seq),
			       DATE_SUB(NOW(6), INTERVAL 500 DAY), NOW(6), 'Administrator', 'Administrator', 0, 0
			FROM seq_{have + 1}_to_{ITEMS}"""
		),
	)
	timed(
		"bins",
		lambda: db.sql(
			f"""INSERT INTO `tabBin`
			(name, item_code, warehouse, actual_qty, projected_qty, reserved_qty, ordered_qty, planned_qty, indented_qty, stock_uom, valuation_rate, stock_value, {ALL_COLUMNS})
			SELECT CONCAT('BIN-', {code("seq")}), {code("seq")}, '{WAREHOUSE}',
			       CASE WHEN seq % 100 < 5 THEN 2 WHEN seq % 100 < 10 THEN 40 ELSE 300 + seq % 200 END,
			       CASE WHEN seq % 100 < 5 THEN 2 WHEN seq % 100 < 10 THEN 40 ELSE 300 + seq % 200 END,
			       0, 0, 0, 0, 'Nos', 5, 0, {STAMP}, 0, 0
			FROM seq_{have + 1}_to_{ITEMS}"""
		),
	)
else:
	print(f"{have} scale items exist already")

ledger = db.sql("SELECT COUNT(*) FROM `tabStock Ledger Entry` WHERE name LIKE 'SC-SLE-%'")[0][0]
if ledger < ITEMS * PER_ITEM:
	print(f"ledger rows now: {ledger:,}; wanted {ITEMS * PER_ITEM:,}")
	start = time.time()
	for low in range(1, ITEMS + 1, CHUNK):
		high = min(low + CHUNK - 1, ITEMS)
		if db.sql(f"SELECT 1 FROM `tabStock Ledger Entry` WHERE name = 'SC-SLE-{low:06d}-{PER_ITEM:03d}'"):
			continue  # this chunk is there
		db.sql(
			f"""INSERT INTO `tabStock Ledger Entry`
			(name, item_code, warehouse, posting_date, posting_time, posting_datetime, actual_qty, qty_after_transaction, voucher_type, voucher_no, voucher_detail_no, company,
			 stock_uom, is_cancelled, valuation_rate, incoming_rate, stock_value, stock_value_difference, {ALL_COLUMNS})
			SELECT CONCAT('SC-SLE-', LPAD(a.seq, 6, '0'), '-', LPAD(b.seq, 3, '0')), {code("a.seq")}, '{WAREHOUSE}',
			       DATE_SUB(CURDATE(), INTERVAL ((a.seq * 7 + b.seq * 13) % 470 + 1) DAY), '10:00:00',
			       TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL ((a.seq * 7 + b.seq * 13) % 470 + 1) DAY), '10:00:00'),
			       CASE WHEN b.seq % 7 = 0 THEN 50 ELSE -(1 + (a.seq + b.seq) % 9) END, 100,
			       CASE WHEN b.seq % 7 = 0 THEN 'Purchase Receipt' ELSE 'Delivery Note' END,
			       CONCAT(CASE WHEN b.seq % 7 = 0 THEN 'MAT-PRE-' ELSE 'MAT-DN-' END, a.seq, '-', b.seq), '',
			       '{COMPANY}', 'Nos', 0, 5, 5, 0, 0, {STAMP}, 1, 0
			FROM seq_{low}_to_{high} a JOIN seq_1_to_{PER_ITEM} b"""
		)
		db.commit()
		if (low // CHUNK) % 5 == 0:
			print(f"  items up to {high}: {time.time() - start:.0f} s")
	print(f"ledger: {time.time() - start:.1f} s")
else:
	print(f"{ledger:,} scale ledger rows exist already")

print("items:", db.sql("SELECT COUNT(*) FROM `tabItem` WHERE name LIKE 'SC-%'")[0][0])
print("bins:", db.sql("SELECT COUNT(*) FROM `tabBin`")[0][0])
print("ledger rows:", db.sql("SELECT COUNT(*) FROM `tabStock Ledger Entry`")[0][0])
db.sql("ANALYZE TABLE `tabStock Ledger Entry`, `tabItem`, `tabBin`")
