import frappe
from ai_munimji_engine.core.common import iso, utcnow

from ai_munimji import last_run, wiring
from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.stores import frappe_core_stores, locks

LOG = "ai_munimji"
STOCK_CHECK = last_run.STOCK_CHECK
LEASE_MINUTES = 10  # a run whose lease is not renewed in this time is taken for dead, and the next tick may go. A run renews it at the end of every batch, of every stage (a batch of 200 items takes seconds)
BATCH_SIZE = 200  # items read and analysed together, and then requests raised for, between two commits: the most that one batch holds locked, and the most one failure takes back
BATCH_SECONDS = 0.5  # and a batch that writes (raising requests, proposing orders) is also ended after this long: a person answering a request the run has just replaced waits for the commit
QUEUE = (
	"long"  # the scheduler's own queue ends a job after 300 seconds; the long queue takes the timeout below
)
RUN_TIMEOUT = (
	6 * 60 * 60
)  # seconds: a site of tens of thousands of items takes minutes, not hours; this only stops a run that is stuck
QUEUE_JOB_ID = "ai_munimji:stock_check"
MAX_SEAL_SWEEPS = 50  # of at most stores.core.SEAL_BATCH records each, in one run: a backlog is cleared over several runs, so that a run's cost never depends on it
# What a Job Run says about how far a run has got, by stage (the engine's own stage names: inventory/agent.py, procurement/agent.py). Plain English: it is a record, not a screen.
PROGRESS = {
	"starting": "Starting",
	"planning": "Worked out the settings of {done} of {total} items",
	"checking": "Read and analysed {done} of {total} items",
	"raising": "Looked at {done} of {total} analysed items for requests to raise",
	"proposing": "Prepared {done} of {total} approved reorders for a supplier",
	"sealing": "Sealed {done} records",
	"finished": "Finished",
}


def system_erp(company: str | None = None) -> FrappeERPClient:
	"""The ERP client in its named system mode, for the scheduled job: Frappe runs a job as Administrator, which may read what a person may not (the Tax Rules, to keep the tax
	figures with a proposal). The mode reads only and never makes a document. This is the one place it is built: tests/test_rules.py fails if it is built anywhere else."""
	return FrappeERPClient(system=True, company=company)


def system_stores():
	"""The DocType stores in their named system mode: Administrator only, and the only mode that may append to the audit seal. Built here and nowhere else (tests/test_rules.py)."""
	return frappe_core_stores(system=True)


def system_services(clock=None, company: str | None = None) -> wiring.Services:
	"""The engine's services as the scheduled job runs them: it reads ERPNext as the system-mode client and keeps its records in the system-mode stores."""
	return wiring.build(system_erp(company), system_stores(), clock)


def commit() -> None:
	"""What the job keeps so far. One place, so that a test that must not commit says so in one place (tests/test_jobs.py)."""
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - the point of a batch: what it did is kept, its locks go, and a later failure takes back only the batch it happens in


class Checkpoint:
	"""What a run does at the end of each batch of its work: keep its lease, note how far it has got, and commit. The engine calls it with (stage, done, total) and stops the run if it
	raises (the lease was lost to another run, or the database refused)."""

	def __init__(self, holder: str, jobs) -> None:
		self.holder, self.jobs = holder, jobs

	def __call__(self, stage: str, done: int, total: int) -> None:
		locks.renew(STOCK_CHECK, self.holder, LEASE_MINUTES)
		self.jobs.progress(STOCK_CHECK, PROGRESS[stage].format(done=f"{done:,}", total=f"{total:,}"))
		commit()


def seal_what_is_new(services, checkpoint: Checkpoint) -> int:
	"""Seal the closed requests and settings changes that are not sealed yet, a batch at a time, with a commit after each, until nothing is left or MAX_SEAL_SWEEPS batches have been done.
	Returns how many were sealed. With nothing new this reads a handful of rows, whatever the history holds."""
	sealed = 0
	for _sweep in range(MAX_SEAL_SWEEPS):
		more = services.audit.sweep()
		sealed += more
		if more:
			checkpoint("sealing", sealed, 0)
		else:
			break
	return sealed


def check_stock() -> int:
	"""The scheduled entry (schedule.py): puts the run on the long queue, with a timeout that fits a large site, and returns at once. Does nothing while Watch stock is off. A run that is
	already queued or running is not queued again (and the lease, in `run_stock_check`, keeps two runs from working at once even then). Returns 0: the run reports to its Job Run, not to the
	scheduler."""
	if not frappe.get_cached_doc("AI Munimji Settings").enabled:
		return 0
	frappe.enqueue(
		"ai_munimji.jobs.run_stock_check",
		queue=QUEUE,
		timeout=RUN_TIMEOUT,
		job_id=QUEUE_JOB_ID,
		deduplicate=True,
	)
	return 0


def run_stock_check(
	clock=None,
	company: str | None = None,
	items: list[str] | None = None,
	batch_size: int = BATCH_SIZE,
	batch_seconds: float | None = BATCH_SECONDS,
) -> dict:
	"""One tick of the scheduler: read the stock, raise alerts and requests for what is low, turn the reorders a person has approved into purchase proposals, and seal what has been
	answered since. Rules decide; a person answers. Nothing is ordered here: the job reads ERPNext as the system-mode client, which cannot make a document.

	Does nothing while Watch stock is off (the app's default, docs/NAMES.md), and nothing if another run holds the lease (two ticks at once make one proposal, not two). The lease is taken
	first because it commits. `items` limits the look at the stock to those item codes (a manual check of one item); the purchase proposals are made for every reorder a person has approved.

	The work goes in batches of `batch_size` items, and the stages that write are also cut every `batch_seconds`. After each the job commits, renews its lease and notes in its Job Run how far it got
	(`Checkpoint`), so that no row stays locked for the length of the run, a failure takes back one batch and not the whole run, and a run on a large site does not lose its lease. A run that stops half way and is run again acts on each item
	once: the engine's duplicate checks find what the first run already raised."""
	settings = frappe.get_cached_doc("AI Munimji Settings")
	if not settings.enabled:
		return {"ran": False, "why": "Watch stock is off", "requests": 0}
	holder = frappe.generate_hash(length=10)
	if not locks.lease(STOCK_CHECK, holder, LEASE_MINUTES):
		return {"ran": False, "why": "another run is under way", "requests": 0}
	clock = clock or utcnow
	services = None
	try:
		services = system_services(clock, company)
		services.core.jobs.started(STOCK_CHECK, iso(clock()))
		checkpoint = Checkpoint(holder, services.core.jobs)
		checkpoint("starting", 0, 0)
		inventory = services.inventory.run(
			item_codes=items, batch_size=batch_size, checkpoint=checkpoint, batch_seconds=batch_seconds
		)
		procurement = services.procurement.run(
			batch_size=batch_size, checkpoint=checkpoint, batch_seconds=batch_seconds
		)
		sealed = seal_what_is_new(services, checkpoint)
		# an item the engine could not analyse is skipped so that the others are looked at; the run went well, and the count is kept with it for the Settings page (last_run.py)
		skipped = last_run.unanalysed_items(inventory.errors)
		services.core.jobs.finished(STOCK_CHECK, iso(clock()), True, last_run.note(len(skipped)))
		services.core.jobs.progress(STOCK_CHECK, PROGRESS["finished"])
		if skipped:
			shown = ", ".join(skipped[:20]) + (f" and {len(skipped) - 20} more" if len(skipped) > 20 else "")
			frappe.logger(LOG).warning(f"run_stock_check could not analyse {len(skipped)} item(s): {shown}")
		# the last batch is committed by the caller: Frappe's scheduler (and a queued job) commits one that returns, and rolls back one that raises, which takes back only what the last batch
		# wrote (the failure is recorded below, which is why that one commits)
		report = {
			"ran": True,
			"requests": inventory.new_alerts
			+ inventory.new_notices
			+ procurement.proposed
			+ procurement.manual,
			"alerts": inventory.new_alerts,
			"notices": inventory.new_notices,
			"considered": procurement.considered,
			"proposals": procurement.proposed,
			"manual": procurement.manual,
			"unanalysed": len(skipped),
			"errors": [*inventory.errors, *procurement.errors],
			"actions": [
				*inventory.actions,
				*procurement.actions,
			],  # what was done, item by item, in the engine's own words
			"sealed": sealed,
		}
		frappe.logger(LOG).info(
			f"run_stock_check ran as {frappe.session.user}: {report['requests']} request(s), {sealed} sealed"
		)
		return report
	except locks.LeaseLost:
		frappe.db.rollback()  # only the batch under way: the batches before it are kept
		frappe.log_error(title="AI Munimji: the stock check lost its lease and stopped")
		raise
	except Exception as exc:
		frappe.db.rollback()  # only the batch under way: the batches before it are kept
		if services is not None:
			try:
				services.core.jobs.finished(
					STOCK_CHECK, iso(clock()), False, f"{type(exc).__name__}: {exc}"[:200]
				)
				commit()
			except Exception:
				frappe.db.rollback()
		frappe.log_error(title="AI Munimji: the stock check failed")
		raise
	finally:
		locks.release(STOCK_CHECK, holder)
