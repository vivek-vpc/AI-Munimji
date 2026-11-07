import frappe
from ai_munimji_engine.core.common import iso, utcnow

from ai_munimji import wiring
from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.stores import frappe_core_stores, locks

LOG = "ai_munimji"
STOCK_CHECK = "stock_check"
LEASE_MINUTES = 5  # a run that has not ended in this time is taken for dead, and the next tick may go


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


def check_stock() -> int:
	"""The scheduled entry (hooks.py). Runs the stock check and returns how many requests it made. Phase 5 replaces the hook's schedule with the settings' own cron; what runs is this."""
	report = run_stock_check()
	return int(report.get("requests", 0))


def run_stock_check(clock=None, company: str | None = None, items: list[str] | None = None) -> dict:
	"""One tick of the scheduler: read the stock, raise alerts and requests for what is low, turn the reorders a person has approved into purchase proposals, and seal what has been
	answered since. Rules decide; a person answers. Nothing is ordered here: the job reads ERPNext as the system-mode client, which cannot make a document.

	Does nothing while Watch stock is off (the app's default, docs/NAMES.md), and nothing if another run holds the lease (two ticks at once make one proposal, not two). The lease is taken
	first because it commits. `items` limits the look at the stock to those item codes (a manual check of one item); the purchase proposals are made for every reorder a person has approved."""
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
		inventory = services.inventory.run(item_codes=items)
		procurement = services.procurement.run()
		sealed = services.audit.sweep()
		services.core.jobs.finished(STOCK_CHECK, iso(clock()), True, None)
		# no commit here: Frappe's scheduler commits a job that returns, and rolls back one that raises (the failure is recorded below, which is why that one commits)
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
	except Exception as exc:
		frappe.db.rollback()
		if services is not None:
			try:
				services.core.jobs.finished(
					STOCK_CHECK, iso(clock()), False, f"{type(exc).__name__}: {exc}"[:200]
				)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
		frappe.log_error(title="AI Munimji: the stock check failed")
		raise
	finally:
		locks.release(STOCK_CHECK, holder)
