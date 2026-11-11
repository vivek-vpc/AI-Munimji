# Adds a few HOT items to a SCALE site's stock ledger (never the development site): items that move many times a day, which is what makes the ledger of a busy site large. The read of the
# consumption used to cost one row per movement, so these items are what the review's finding is about. Run after seed_scale.py:
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_hot.py 3 100000
# The two numbers: how many items (the first ones, SC-000001...) and how many movements each. Run again and it adds nothing.
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
HOT = int(args[0]) if args else 3
MOVEMENTS = int(args[1]) if len(args) > 1 else 100000
COMPANY, WAREHOUSE = "Munimji Demo Co", "Stores - MDC"
db = frappe.db
start = time.time()
for item in range(1, HOT + 1):
	code = f"SC-{item:06d}"
	if db.sql(f"SELECT 1 FROM `tabStock Ledger Entry` WHERE name = 'SC-SLE-HOT-{code}-{MOVEMENTS:07d}'"):
		continue
	db.sql(
		f"""INSERT INTO `tabStock Ledger Entry`
		(name, item_code, warehouse, posting_date, posting_time, posting_datetime, actual_qty, qty_after_transaction, voucher_type, voucher_no, voucher_detail_no, company,
		 stock_uom, is_cancelled, valuation_rate, incoming_rate, stock_value, stock_value_difference, to_rename, creation, modified, modified_by, owner, docstatus, idx)
		SELECT CONCAT('SC-SLE-HOT-{code}-', LPAD(seq, 7, '0')), '{code}', '{WAREHOUSE}',
		       DATE_SUB(CURDATE(), INTERVAL ((seq * 7) % 470 + 1) DAY), '11:00:00', TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL ((seq * 7) % 470 + 1) DAY), '11:00:00'),
		       -(1 + seq % 9), 100, 'Delivery Note', CONCAT('MAT-DN-HOT-{code}-', seq), '', '{COMPANY}', 'Nos', 0, 0, 5, 5, 0, 0, NOW(6), NOW(6), 'Administrator', 'Administrator', 1, 0
		FROM seq_1_to_{MOVEMENTS}"""
	)
	db.commit()
	print(f"{code}: {MOVEMENTS:,} movements, {time.time() - start:.0f} s", flush=True)
print("ledger rows:", db.sql("SELECT COUNT(*) FROM `tabStock Ledger Entry`")[0][0])
