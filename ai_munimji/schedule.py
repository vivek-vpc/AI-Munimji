import frappe

METHOD = "ai_munimji.jobs.check_stock"
AGAINST = "AI Munimji Settings"
DEFAULT_CRON = "0 6 * * *"  # the Settings page's own default


def sync(enabled: bool, cron: str | None) -> str:
	"""Make the stock check's scheduled job exist and say what the Settings page says: stopped while Watch stock is off, and the page's schedule in cron form. Returns the job's name.
	Running it again with the same values changes nothing.

	The job is a Scheduled Job Type LINKED TO A SCHEDULER EVENT, not declared in hooks.py. Frappe's migrate puts every hook-declared job back to the hook's schedule and deletes every
	job that no hook, Server Script or Scheduler Event stands behind (core/doctype/scheduled_job_type), so a schedule that a person edited on the Settings page would be lost at the
	next `bench migrate`. Frappe's own System Settings does the same for its sync job.

	A Munimji Manager may save the Settings page but holds no right on Frappe's job records, so this is the one place, besides the install hooks, that writes with ignore_permissions
	(tests/test_rules.py names it). It writes one job, whose method is a constant of this module and whose schedule croniter has already read (settings_map.validate)."""
	cron = (cron or "").strip() or DEFAULT_CRON
	event = frappe.db.exists("Scheduler Event", {"scheduled_against": AGAINST, "method": METHOD})
	if not event:
		event = (
			frappe.get_doc({"doctype": "Scheduler Event", "scheduled_against": AGAINST, "method": METHOD})
			.insert(ignore_permissions=True)
			.name
		)
	wanted = {
		"frequency": "Cron",
		"cron_format": cron,
		"scheduler_event": event,
		"create_log": 1,
		"stopped": 0 if enabled else 1,
	}
	name = frappe.db.exists("Scheduled Job Type", {"method": METHOD})
	if not name:
		return (
			frappe.get_doc({"doctype": "Scheduled Job Type", "method": METHOD, **wanted})
			.insert(ignore_permissions=True)
			.name
		)
	job = frappe.get_doc("Scheduled Job Type", name)
	if any(job.get(key) != value for key, value in wanted.items()):
		job.update(wanted)
		job.save(ignore_permissions=True)
	return name


def remove() -> None:
	"""Take the job and its Scheduler Event out (uninstall)."""
	for name in frappe.db.get_values("Scheduled Job Type", {"method": METHOD}, "name", pluck=True):
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)
	for name in frappe.db.get_values(
		"Scheduler Event", {"scheduled_against": AGAINST, "method": METHOD}, "name", pluck=True
	):
		frappe.delete_doc("Scheduler Event", name, force=True, ignore_permissions=True)
