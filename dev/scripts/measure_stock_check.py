# Measures one stock check on a SCALE site (never the development site): how long it takes, its peak memory, how long it holds row locks, and how long a person's answer takes while it runs.
# The numbers go to docs/SCALE_MEASUREMENTS.md. Run (inside the container):
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/measure_stock_check.py <items> [dismiss|approve|none]
#
#   items   how many of the seeded items the run looks at (the others are switched off)
#   answer  what the person does to each of the 20 requests the run is about to replace, as soon as the run has begun to replace them, one every 0.1 s: "dismiss" (waits on the row only),
#           "approve" (the whole answer: it also reads the item again and makes a work order), or "none"
#
# The set-up is the same every time: 20 requests wait for items that were low (their stock is then set to 0, so that the run raises a worse alert for each and replaces the old request,
# which is a write to the very row a person is answering), and the other items are as the seed made them: 5 in 100 nearly out of stock, 5 in 100 low, the rest plenty.
import json
import resource
import statistics
import threading
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from ai_munimji import jobs, wiring
from ai_munimji.stores import locks
from ai_munimji.stores.specs import TABLES

ITEMS = int(args[0]) if args else 5000
ANSWER = args[1] if len(args) > 1 else "dismiss"
SAMPLE_EVERY = 0.1  # seconds between looks at the database's transaction list
TOUCHED = 6  # rows one transaction has written when the run is taken to have begun raising requests (starting a Job Run writes one or two)
APPROVER = "munimji.approver@example.com"
WATCHED = [
	f"SC-{base + n:06d}" for base in (0, 100, 200, 300) for n in range(5, 10)
]  # 20 items, each of the "low" kind (item number MOD 100 between 5 and 9)
db = frappe.db
site, sites_path = frappe.local.site, frappe.local.sites_path


def prepare():
	frappe.set_user("Administrator")
	for table in TABLES:
		db.delete(table.doctype)
	locks.ensure()
	settings = frappe.get_doc("AI Munimji Settings")
	settings.enabled, settings.min_qty, settings.min_days_cover, settings.stock_alerts = 1, 0, 30, 0
	settings.save()
	db.sql(
		"UPDATE `tabItem` SET disabled = IF(CAST(SUBSTRING(name, 4) AS UNSIGNED) > %s, 1, 0) WHERE name LIKE 'SC-%%'",
		(ITEMS,),
	)
	db.sql(
		"UPDATE `tabBin` SET actual_qty = IF(name IN %s, 40, actual_qty), projected_qty = IF(name IN %s, 40, projected_qty) WHERE name LIKE 'BIN-SC-%%'",
		(tuple(f"BIN-{c}" for c in WATCHED),) * 2,
	)
	db.commit()
	frappe.clear_cache()
	first = jobs.run_stock_check(items=WATCHED)  # the 20 low items get a request each
	db.commit()
	waiting = frappe.get_all(
		"Munimji Approval Request", filters={"status": "pending", "item_code": ["in", WATCHED]}, pluck="name"
	)
	assert len(waiting) == len(WATCHED), (len(waiting), first["errors"][:2], first["alerts"])
	db.sql(
		"UPDATE `tabBin` SET actual_qty = 0, projected_qty = 0 WHERE name IN %s",
		(tuple(f"BIN-{c}" for c in WATCHED),),
	)
	db.commit()
	return waiting


def own_connection():
	frappe.init(site=site, sites_path=sites_path)
	frappe.connect()


class Sampler(threading.Thread):
	"""Looks at the database's transaction list every 0.1 s (as the database's root user: the site's own user may not) and writes down, for one connection, each transaction that held row locks
	and for how long. `locking` is set when the run's transaction has written TOUCHED rows (it has begun to raise and replace requests)."""

	def __init__(self, connection_id, host):
		super().__init__(daemon=True)
		self.connection_id, self.host, self.stop, self.seen, self.samples = (
			connection_id,
			host,
			threading.Event(),
			{},
			0,
		)
		self.locking = threading.Event()

	def run(self):
		import MySQLdb

		root = MySQLdb.connect(host=self.host, user="root", passwd="123")
		cursor = root.cursor()
		while not self.stop.is_set():
			now = time.time()
			cursor.execute(
				"SELECT trx_id, trx_lock_structs, trx_rows_modified FROM information_schema.innodb_trx WHERE trx_mysql_thread_id = %s",
				(self.connection_id,),
			)
			for trx, structs, modified in cursor.fetchall():
				if structs or modified:
					first, _last = self.seen.get(trx, (now, now))
					self.seen[trx] = (first, now)
					if modified >= TOUCHED:
						self.locking.set()
			self.samples += 1
			root.commit()
			time.sleep(SAMPLE_EVERY)
		root.close()

	def holds(self):
		"""Seconds each lock-holding transaction was seen holding, longest first (resolution: the sampling interval)."""
		return sorted((last - first + SAMPLE_EVERY for first, last in self.seen.values()), reverse=True)


class Person(threading.Thread):
	"""Answers the watched requests, one every 0.1 s, each on a connection of its own, from the moment the run has begun to replace them (the run replaces these requests as its first work, so a
	person answering them then is answering a request the run has touched and not yet committed)."""

	def __init__(self, waiting, sampler):
		super().__init__(daemon=True)
		self.waiting, self.sampler, self.stop, self.timings, self.threads = (
			list(waiting),
			sampler,
			threading.Event(),
			[],
			[],
		)

	def answer(self, name):
		started = time.time()
		try:
			own_connection()
			frappe.set_user(APPROVER)
			action = "approve" if ANSWER == "approve" else "dismiss"
			result = wiring.person_services().approvals.decide(
				name, action, wiring.actor_for(APPROVER), "desk"
			)
			frappe.db.commit()
			outcome = f"{result.status}"
		except BaseException as exc:
			frappe.db.rollback()
			outcome = f"{type(exc).__name__}"
		finally:
			frappe.destroy()
		self.timings.append((round(started - T0, 1), round(time.time() - started, 2), outcome))

	def run(self):
		while not self.sampler.locking.wait(0.05):
			if self.stop.is_set():
				return
		for name in self.waiting:
			thread = threading.Thread(target=self.answer, args=(name,), daemon=True)
			thread.start()
			self.threads.append(thread)
			if self.stop.wait(0.1):
				break


T0 = time.time()
STAGES: dict[
	str, list[float]
] = {}  # stage -> the times (seconds since the run began) at which it reported, for "where did the time go"
real_call = jobs.Checkpoint.__call__ if hasattr(jobs, "Checkpoint") else None
if real_call is not None:

	def timed_call(self, stage, done, total):
		STAGES.setdefault(stage, []).append(round(time.time() - T0, 1))
		return real_call(self, stage, done, total)

	jobs.Checkpoint.__call__ = timed_call


def run_check():
	started = time.time()
	report = jobs.run_stock_check()
	return report, time.time() - started


waiting = prepare()
print(f"set up: {ITEMS} items looked at, {len(waiting)} requests waiting for answers", flush=True)
connection_id = db.sql("SELECT CONNECTION_ID()")[0][0]
sampler = Sampler(connection_id, frappe.conf.db_host or "mariadb")
person = Person(waiting, sampler)
rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
sampler.start()
STAGES.clear()  # the set-up's own check is not the run being measured
T0 = time.time()
if ANSWER != "none":
	person.start()
report, seconds = run_check()
person.join(5)
for thread in person.threads:
	thread.join(
		120
	)  # an answer that is still waiting when the run ends gets its answer then; the wait is what is measured
person.stop.set()
sampler.stop.set()
sampler.join(5)
holds = sampler.holds()
waits = [t for _, t, _ in person.timings]
slowest = max(waits, default=0)
print(
	json.dumps(
		{
			"items": ITEMS,
			"seconds": round(seconds, 1),
			"peak_memory_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
			"memory_before_run_mb": rss_before,
			"requests_made": report.get("requests"),
			"alerts": report.get("alerts"),
			"unanalysed": report.get("unanalysed"),
			"lock_holding_transactions_seen": len(holds),
			"longest_lock_hold_s": round(holds[0], 1) if holds else 0,
			"lock_holds_s_top5": [round(h, 1) for h in holds[:5]],
			"answers": len(waits),
			"answer_seconds_median": round(statistics.median(waits), 2) if waits else None,
			"answer_seconds_slowest": slowest,
			"answers_over_2s": sum(1 for w in waits if w > 2),
			"answer_outcomes": sorted({o for _, _, o in person.timings}),
			"stages_first_and_last_report_s": {k: [v[0], v[-1], len(v)] for k, v in STAGES.items()},
			"answer_timeline": person.timings,
		},
		indent=1,
	)
)
