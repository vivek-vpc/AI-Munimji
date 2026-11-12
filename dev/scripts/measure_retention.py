# Measures the daily clean-up of the logs on a SCALE site (never the development site): it writes <n> tool calls older than the retention period (raw SQL, as the first backlog of a site
# that has never been cleaned up) and then runs retention.clean_up the way the scheduler does, one run after another, and says how many records each run removed and how long it took.
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/measure_retention.py <n> [runs]
import json
import time
from datetime import UTC, datetime, timedelta

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from ai_munimji import retention
from ai_munimji.stores.core import Context

N = int(args[0]) if args else 5000
RUNS = int(args[1]) if len(args) > 1 else 3
db = frappe.db
table = Context().table("tool_calls")
STAMP = ("creation", "modified", "modified_by", "owner", "docstatus", "idx")

db.sql(f"TRUNCATE TABLE `tab{table.doctype}`")
base = datetime.now(UTC) - timedelta(days=400)
for low in range(0, N, 2000):
	rows = []
	for i in range(low, min(low + 2000, N)):
		row = {
			"id": i + 1,
			"at": (base + timedelta(seconds=i)).replace(microsecond=0).isoformat(),
			"actor": "munimji.approver@example.com",
			"via": "desk",
			"tool": "get_stock",
			"args_json": "{}",
			"ok": 1,
			"ms": 5,
			"task_id": None,
			"error": None,
		}
		rows.append(
			{
				"name": str(i + 1),
				**table.values(row),
				**dict(
					zip(
						STAMP,
						(row["at"][:19].replace("T", " "),) * 2 + ("Administrator", "Administrator", 0, 0),
						strict=True,
					)
				),
			}
		)
	names = list(rows[0])
	db.bulk_insert(table.doctype, names, [tuple(r[n] for n in names) for r in rows])
db.commit()
print(f"{N:,} expired tool calls written", flush=True)

results = []
for run in range(RUNS):
	before = db.sql(f"SELECT COUNT(*) FROM `tab{table.doctype}`")[0][0]
	started = time.time()
	try:
		gone = retention.clean_up(keep_days=90)
		db.commit()
		outcome = "ok"
	except BaseException as exc:
		db.rollback()
		gone, outcome = None, f"{type(exc).__name__}: {str(exc)[:80]}"
	left = db.sql(f"SELECT COUNT(*) FROM `tab{table.doctype}`")[0][0]
	results.append(
		{
			"run": run + 1,
			"seconds": round(time.time() - started, 1),
			"removed": before - left,
			"left": left,
			"outcome": outcome,
		}
	)
	print(json.dumps(results[-1]), flush=True)
	if left == 0:
		break
