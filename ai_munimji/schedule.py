import frappe

METHOD = "ai_munimji.jobs.check_stock"
CLEAN_UP = "ai_munimji.retention.clean_up"  # the daily clean-up of the logs (retention.py)
METHODS = (METHOD, CLEAN_UP)
AGAINST = "AI Munimji Settings"
DEFAULT_CRON = "0 6 * * *"  # the Settings page's own default


def _ensure(method: str, wanted: dict) -> str:
	"""The Scheduled Job Type for `method`, standing on its Scheduler Event, with the values in `wanted`. Made if missing; changed only when a value differs. Returns its name."""
	event = frappe.db.exists("Scheduler Event", {"scheduled_against": AGAINST, "method": method})
	if not event:
		event = (
			frappe.get_doc({"doctype": "Scheduler Event", "scheduled_against": AGAINST, "method": method})
			.insert(ignore_permissions=True)
			.name
		)
	wanted = {**wanted, "scheduler_event": event, "create_log": 1}
	name = frappe.db.exists("Scheduled Job Type", {"method": method})
	if not name:
		return (
			frappe.get_doc({"doctype": "Scheduled Job Type", "method": method, **wanted})
			.insert(ignore_permissions=True)
			.name
		)
	job = frappe.get_doc("Scheduled Job Type", name)
	if any(job.get(key) != value for key, value in wanted.items()):
		job.update(wanted)
		job.save(ignore_permissions=True)
	return name


def sync(enabled: bool, cron: str | None) -> str:
	"""Make the stock check's scheduled job exist and say what the Settings page says: stopped while Watch stock is off, and the page's schedule in cron form. Returns the job's name.
	Running it again with the same values changes nothing.

	The job is a Scheduled Job Type LINKED TO A SCHEDULER EVENT, not declared in hooks.py. Frappe's migrate puts every hook-declared job back to the hook's schedule and deletes every
	job that no hook, Server Script or Scheduler Event stands behind (core/doctype/scheduled_job_type), so a schedule that a person edited on the Settings page would be lost at the
	next `bench migrate`. Frappe's own System Settings does the same for its sync job.

	A Munimji Manager may save the Settings page but holds no right on Frappe's job records, so this is the one place, besides the install hooks, that writes with ignore_permissions
	(tests/test_rules.py names it). It writes two jobs (this one and the clean-up's), whose methods are constants of this module and whose schedule croniter has already read
	(settings_map.validate).

	A page saved by an earlier version may still hold a schedule that starts the check more often than the page now allows (it was never refused). The job does not follow it: it runs at the
	page's default time and the saved expression is left for a person to correct, with a warning in the log, so that an old setting cannot start back-to-back runs of the whole stock."""
	from croniter import croniter

	from ai_munimji import (
		settings_map,  # here: this module must still load, for the uninstall, in a bench from which the engine has been removed
	)

	cron = (cron or "").strip() or DEFAULT_CRON
	if (
		len(cron.split()) == 5
		and croniter.is_valid(cron)
		and settings_map.shortest_gap_minutes(cron) < settings_map.MIN_MINUTES_BETWEEN_CHECKS
	):
		frappe.logger("ai_munimji").warning(
			f"the saved schedule “{cron}” starts the stock check more often than every {settings_map.MIN_MINUTES_BETWEEN_CHECKS} minutes; the job runs at {DEFAULT_CRON} until it is changed"
		)
		cron = DEFAULT_CRON
	return _ensure(METHOD, {"frequency": "Cron", "cron_format": cron, "stopped": 0 if enabled else 1})


def sync_clean_up(keep_logs_days: int | None) -> str:
	"""Make the daily clean-up of the logs exist, running while "Keep logs for (days)" is a positive number and stopped while it is 0 (keep everything). A page that holds no number (saved before
	the field existed) means the default, as retention.clean_up reads it. "Daily Long": the clean-up deletes record by record and may take longer than a short job is allowed. It never
	touches a request, a proposal, an alert or the audit seal (retention.py). Returns the job's name."""
	from ai_munimji.settings_map import (
		KEEP_LOGS_DEFAULT,  # here: this module must still load, for the uninstall, in a bench from which the engine has been removed
	)

	days = KEEP_LOGS_DEFAULT if keep_logs_days is None else int(keep_logs_days)
	return _ensure(CLEAN_UP, {"frequency": "Daily Long", "stopped": 0 if days > 0 else 1})


def remove() -> None:
	"""Take the jobs and their Scheduler Events out (uninstall)."""
	for name in frappe.db.get_values("Scheduled Job Type", {"method": ["in", METHODS]}, "name", pluck=True):
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)
	for name in frappe.db.get_values(
		"Scheduler Event", {"scheduled_against": AGAINST, "method": ["in", METHODS]}, "name", pluck=True
	):
		frappe.delete_doc("Scheduler Event", name, force=True, ignore_permissions=True)
