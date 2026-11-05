# EXPERIMENT (measurement only): two scheduled jobs that only write the time they ran, to see (1) how often the scheduler really calls a per-minute
# cron job and (2) which kind of job survives `bench migrate`:
#   A: a plain Scheduled Job Type, cron "* * * * *"       (like the ones hooks.py creates)
#   B: a Scheduled Job Type linked to a Scheduler Event, cron "*/2 * * * *"   (the "configurable" kind in the documentation)
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/cadence_start.py
def make(method, cron, scheduler_event=None):
	if frappe.db.exists("Scheduled Job Type", {"method": method, "cron_format": cron}):
		return
	job = {"doctype": "Scheduled Job Type", "method": method, "frequency": "Cron", "cron_format": cron}
	if scheduler_event:
		job["scheduler_event"] = scheduler_event
	frappe.get_doc(job).insert()


make("ai_munimji.jobs.tick_probe", "* * * * *")

event = frappe.db.get_value("Scheduler Event", {"method": "ai_munimji.jobs.tick_probe_b"})
if not event:
	event = frappe.get_doc({"doctype": "Scheduler Event", "scheduled_against": "AI Munimji Settings", "method": "ai_munimji.jobs.tick_probe_b"}).insert().name
make("ai_munimji.jobs.tick_probe_b", "*/2 * * * *", scheduler_event=event)

from frappe.utils.scheduler import enable_scheduler  # noqa: E402

enable_scheduler()
print("jobs:", frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ai_munimji%"]}, fields=["method", "cron_format", "scheduler_event"]))
print("scheduler enabled:", not frappe.utils.scheduler.is_scheduler_disabled() if hasattr(frappe.utils.scheduler, "is_scheduler_disabled") else "unknown")
