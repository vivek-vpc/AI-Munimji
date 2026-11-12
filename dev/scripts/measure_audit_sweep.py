# Measures what the audit sweep costs when there is nothing new to seal, on a SCALE site that seed_audit.py has filled (never the development site): time and rows fetched into Python.
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/measure_audit_sweep.py
import json
import resource
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from ai_munimji import jobs, wiring
from ai_munimji.erp_client import FrappeERPClient

rows = {"fetched": 0, "queries": 0}
real_get_list = frappe.get_list


def counting_get_list(*a, **kw):
	got = real_get_list(*a, **kw)
	rows["fetched"] += len(got)
	rows["queries"] += 1
	return got


frappe.get_list = counting_get_list
core = jobs.system_stores()
services = wiring.build(FrappeERPClient(system=True), core)
closed = frappe.db.sql("SELECT COUNT(*) FROM `tabMunimji Approval Request` WHERE status != 'pending'")[0][0]
sealed = frappe.db.sql("SELECT COUNT(*) FROM `tabMunimji Audit Seal`")[0][0]
start_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
results = []
for _ in range(3):  # the first call may find the tables cold; the third is the usual one
	rows.update(fetched=0, queries=0)
	started = time.time()
	made = services.audit.sweep()
	results.append(
		{
			"sealed_by_it": made,
			"seconds": round(time.time() - started, 2),
			"rows_fetched_into_python": rows["fetched"],
			"queries": rows["queries"],
		}
	)
print(
	json.dumps(
		{
			"closed_requests": closed,
			"seal_entries": sealed,
			"memory_at_start_mb": start_memory,
			"peak_memory_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
			"sweeps_with_nothing_new": results,
		},
		indent=1,
	)
)
