"""Reads the worker log of the scheduler experiment and prints when each job ran (as which user) and the gaps between runs.
    python3 cadence_report.py <path to logs/worker.log>   (inside the container: /home/frappe/dev/frappe-bench/logs/worker.log)
The app's own log lines are not used: frappe.logger(...).info() writes nothing unless the log level is raised (the default is WARNING on a dev server, ERROR otherwise).
"""
import re
import sys
from datetime import datetime

runs = {}
for line in open(sys.argv[1]):
	m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ Successfully completed .*?'job_type': '(ai_munimji\.jobs\.\w+)'.*?user='(\w+)'", line)
	if m:
		runs.setdefault(m.group(2), []).append((datetime.fromisoformat(m.group(1).replace(" ", "T")), m.group(3)))

for name, items in sorted(runs.items()):
	times = [t for t, _ in items]
	gaps = [round((b - a).total_seconds()) for a, b in zip(times, times[1:])]
	print(f"{name}: {len(items)} runs as {sorted({u for _, u in items})}")
	print("  at   :", " ".join(t.strftime("%H:%M:%S") for t in times[:40]))
	print("  gaps :", gaps[:40], "seconds", f"(min {min(gaps)}, max {max(gaps)})" if gaps else "")
