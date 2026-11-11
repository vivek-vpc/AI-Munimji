"""Load test of what a crowd of approvers does to the app, over HTTP, against a running bench (the production-readiness review, finding A5). Run it inside the container, after
dev/scripts/seed_load.py has made the people and the requests:

    python3 /workspace/ai_munimji/dev/loadtest.py --base http://127.0.0.1:8001 --site scale.localhost <a|b|c|all>

  a   100 approvals of 100 different requests at the same moment, each by a different signed-in approver
  b   20 presses on the same request at the same moment (20 different approvers)
  c   100 approvers open the request list and a request form while a stock check runs

Each person is a real user of the site and calls the same URLs the Desk calls, with the user's own API key (the Desk's cookie session needs a browser's CSRF token; the key is what a script
uses, and it is the same user to the permission system). It prints, per scenario: how many answered how, the response time at the 50th and the 95th percentile (and the slowest), how many
were told "busy", and, for the answers, whether any request got two orders (duplicates) or an answer was lost (told ok, but nothing recorded).
Everything runs through `requests` and threads; the only thing it imports from the bench is nothing: the checks of the database go through bench's own mysql client.
"""

import argparse
import json
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

USERS = json.load(open("/tmp/load-users.json"))
REQUESTS = json.load(open("/tmp/load-requests.json"))
LOGINS = list(USERS.items())
SITE_DB = None


def headers(site: str, key: str) -> dict:
	return {"Authorization": f"token {key}", "Host": f"{site}:8000", "X-Frappe-Site-Name": site}


def percentile(values: list[float], pct: float) -> float:
	ordered = sorted(values)
	return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))] if ordered else 0.0


def summary(label: str, results: list[dict]) -> dict:
	times = [r["seconds"] for r in results]
	by_status: dict[str, int] = {}
	for r in results:
		by_status[r["status"]] = by_status.get(r["status"], 0) + 1
	out = {
		"scenario": label,
		"people": len(results),
		"outcomes": dict(sorted(by_status.items())),
		"busy": by_status.get("busy", 0),
		"p50_s": round(statistics.median(times), 2) if times else None,
		"p95_s": round(percentile(times, 95), 2),
		"slowest_s": round(max(times), 2) if times else None,
	}
	return out


def press(base: str, site: str, key: str, approval: str, action: str = "approve", barrier=None) -> dict:
	if barrier is not None:
		barrier.wait(120)
	started = time.time()
	try:
		r = requests.post(
			f"{base}/api/method/ai_munimji.api.answer",
			headers=headers(site, key),
			data={"approval_id": approval, "action": action},
			timeout=290,
		)
		body = (
			r.json().get("message")
			if r.headers.get("content-type", "").startswith("application/json")
			else None
		)
		status = body.get("status") if isinstance(body, dict) else f"http {r.status_code}"
		ok = bool(body.get("ok")) if isinstance(body, dict) else False
	except Exception as exc:
		status, ok, body = f"{type(exc).__name__}", False, None
	return {
		"seconds": time.time() - started,
		"status": status,
		"ok": ok,
		"approval": approval,
		"message": body,
	}


def sql(db: str, text: str) -> list[list[str]]:
	out = subprocess.run(
		["mysql", "-h", "mariadb", "-uroot", "-p123", db, "-N", "-B", "-e", text],
		capture_output=True,
		text=True,
		check=True,
	).stdout
	return [line.split("\t") for line in out.splitlines() if line]


def database_of(site: str) -> str:
	return json.load(open(f"/home/frappe/dev/frappe-bench/sites/{site}/site_config.json"))["db_name"]


def checks(db: str, approvals: list[str]) -> dict:
	"""What the database holds for these requests: how many are decided, how many orders exist for them (an order carries its proposal's id in custom_agent_ref, and the request names the
	proposal in ref_id), and how many requests have more than one order."""
	quoted = ",".join(f"'{a}'" for a in approvals)
	decided = int(
		sql(
			db,
			f"SELECT COUNT(*) FROM `tabMunimji Approval Request` WHERE name IN ({quoted}) AND status = 'decided'",
		)[0][0]
	)
	per_request = sql(
		db,
		"SELECT r.name, COUNT(p.name) FROM `tabMunimji Approval Request` r LEFT JOIN `tabPurchase Order` p "
		"ON (p.custom_agent_ref = r.ref_id OR p.custom_agent_ref LIKE CONCAT(r.ref_id, '-%')) AND p.docstatus < 2 "
		f"WHERE r.name IN ({quoted}) GROUP BY r.name",
	)
	counts = {name: int(n) for name, n in per_request}
	return {
		"decided": decided,
		"requests_with_an_order": sum(1 for n in counts.values() if n >= 1),
		"orders": sum(counts.values()),
		"duplicates": sum(1 for n in counts.values() if n > 1),
	}


def scenario_a(base, site, db):
	approvals = REQUESTS[:100]
	barrier = threading.Barrier(len(approvals))
	with ThreadPoolExecutor(len(approvals)) as pool:
		futures = [
			pool.submit(press, base, site, LOGINS[i][1], approvals[i], "approve", barrier)
			for i in range(len(approvals))
		]
		results = [f.result() for f in futures]
	frappe_state = checks(db, approvals)
	told_ok = sum(1 for r in results if r["ok"])
	out = {**summary("a: 100 different approvals at the same moment", results), **frappe_state}
	out["told_ok"] = told_ok
	out["lost_answers"] = max(0, told_ok - frappe_state["requests_with_an_order"])
	return out


def scenario_b(base, site, db):
	approval = REQUESTS[100] if len(REQUESTS) > 100 else REQUESTS[-1]
	barrier = threading.Barrier(20)
	with ThreadPoolExecutor(20) as pool:
		futures = [
			pool.submit(press, base, site, LOGINS[i][1], approval, "approve", barrier) for i in range(20)
		]
		results = [f.result() for f in futures]
	frappe_state = checks(db, [approval])
	winners = sum(1 for r in results if r["ok"])
	out = {**summary("b: 20 presses on one request at the same moment", results), **frappe_state}
	out["answered_ok"] = winners
	out["lost_answers"] = 0 if frappe_state["decided"] == 1 and winners >= 1 else 1
	return out


def scenario_c(base, site, db):
	start_check = subprocess.Popen(
		[
			"bash",
			"-c",
			f"cd /workspace/ai_munimji && SITE={site} bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/run_check_for_load.py",
		],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
	)
	time.sleep(3)  # let the run start
	barrier = threading.Barrier(100)

	def look(i):
		key = LOGINS[i][1]
		barrier.wait(120)
		timings = []
		for url, params in (
			(
				"/api/method/frappe.desk.reportview.get",
				{
					"doctype": "Munimji Approval Request",
					"fields": '["name","title","status","qty"]',
					"filters": '[["status","=","pending"]]',
					"limit_page_length": 20,
				},
			),
			(
				"/api/method/frappe.desk.form.load.getdoc",
				{"doctype": "Munimji Approval Request", "name": REQUESTS[(i + 30) % len(REQUESTS)]},
			),
		):
			started = time.time()
			try:
				r = requests.get(base + url, headers=headers(site, key), params=params, timeout=290)
				status = "ok" if r.status_code == 200 else f"http {r.status_code}"
			except Exception as exc:
				status = type(exc).__name__
			timings.append({"seconds": time.time() - started, "status": status, "ok": status == "ok"})
		return timings

	with ThreadPoolExecutor(100) as pool:
		pages = [f.result() for f in [pool.submit(look, i) for i in range(100)]]
	still_running = start_check.poll() is None
	flat = [t for page in pages for t in page]
	out = summary("c: 100 people open the list and a form while a stock check runs", flat)
	out["the_stock_check_was_still_running_when_they_finished"] = still_running
	start_check.wait(1800)
	return out


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--base", default="http://127.0.0.1:8001")
	parser.add_argument("--site", default="scale.localhost")
	parser.add_argument("which", nargs="?", default="all")
	args = parser.parse_args()
	db = database_of(args.site)
	results = []
	for name, fn in (("a", scenario_a), ("b", scenario_b), ("c", scenario_c)):
		if args.which in (name, "all"):
			results.append(fn(args.base, args.site, db))
			print(json.dumps(results[-1], indent=1), flush=True)


main()
