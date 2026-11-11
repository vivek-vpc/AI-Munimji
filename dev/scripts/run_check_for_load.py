# A full stock check on a SCALE site, for scenario c of dev/loadtest.py: it runs while people open the list and a request form. Prints how long it took.
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from ai_munimji import jobs

started = time.time()
report = jobs.run_stock_check()
print(
	f"stock check: {time.time() - started:.1f} s, ran={report.get('ran')}, requests={report.get('requests')}"
)
