# Measures what the ERP client reads from the stock ledger on a SCALE site (never the development site): time, peak memory and rows fetched. The numbers go to
# docs/SCALE_MEASUREMENTS.md. Each measurement is its own process, so that the peak memory is its own:
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/measure_ledger_reads.py consumption 30000
#   ... measure_ledger_reads.py items          # list_items(): the day each item's stock history begins
#
#   consumption <n>   get_consumption for the first n items over the 480 days the stock rules read, in the batches the rules ask for
#   hot               get_consumption for the first three items alone: the hot items of seed_hot.py, 100,000 movements each
#   items             list_items(), which reads the first stock movement of the items
#   one               the lookup of one item (get_items on the app's client, the whole list before it had one): what answering a reorder request pays
import json
import resource
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from datetime import date, timedelta

from ai_munimji.erp_client import FrappeERPClient

what = args[0] if args else "consumption"
count = int(args[1]) if len(args) > 1 else 30000

rows = {"fetched": 0, "calls": 0}
real_get_list = frappe.get_list


def counting_get_list(*a, **kw):
	got = real_get_list(*a, **kw)
	rows["fetched"] += len(got)
	rows["calls"] += 1
	return got


frappe.get_list = counting_get_list
client = FrappeERPClient(system=True)
start_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
started = time.time()
if what == "hot":
	today = date.today()
	result = client.get_consumption(
		["SC-000001", "SC-000002", "SC-000003"], today - timedelta(days=480), today
	)
	detail = {
		"items_with_usage": len(result),
		"days_with_usage": {c: len(d) for c, d in result.items()},
		"total_usage_checksum": round(sum(u.qty for days in result.values() for u in days), 3),
	}
elif what == "one":
	found = (
		client.get_items(["SC-000042"])
		if hasattr(client, "get_items")
		else [i for i in client.list_items() if i.code == "SC-000042"]
	)
	detail = {"found": [i.code for i in found], "created": str(found[0].created) if found else None}
elif what == "consumption":
	codes = [f"SC-{n:06d}" for n in range(1, count + 1)]
	today = date.today()
	result = {}
	for i in range(
		0, len(codes), 500
	):  # the stock rules hand the client the items of one warehouse set together; the client cuts them up itself
		result.update(client.get_consumption(codes[i : i + 500], today - timedelta(days=480), today))
	checksum = round(sum(u.qty for days in result.values() for u in days), 3)
	detail = {"items_with_usage": len(result), "total_usage_checksum": checksum}
else:
	items = client.list_items()
	detail = {
		"items": len(items),
		"with_an_earlier_first_movement": sum(
			1 for i in items if i.created and i.created < date.today() - timedelta(days=480)
		),
	}
print(
	json.dumps(
		{
			"what": what,
			"items_asked_for": count if what == "consumption" else None,
			"seconds": round(time.time() - started, 1),
			"peak_memory_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
			"memory_at_start_mb": start_memory,
			"rows_fetched_into_python": rows["fetched"],
			"queries": rows["calls"],
			**detail,
		},
		indent=1,
	)
)
