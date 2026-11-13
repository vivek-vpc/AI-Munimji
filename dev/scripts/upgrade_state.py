# Used by dev/check-upgrade.sh: what the app has left on this site, as a JSON file, so that two states can be compared by a program.
#   dev/run-script.sh dev/scripts/upgrade_state.py <file.json>
# Read-only. Fields that an older version does not have are None.
import json

import ai_munimji

SETTINGS = (
	"enabled",
	"check_cron",
	"min_qty",
	"reminder_after_hours",
	"keep_logs_days",
	"telegram_enabled",
	"telegram_mode",
	"telegram_bot_username",
)
doc = frappe.get_doc("AI Munimji Settings")
state = {
	"version": ai_munimji.__version__,
	"settings": {name: doc.get(name) for name in SETTINGS},
	"jobs": {
		job.method: {"frequency": job.frequency, "cron": job.cron_format or "", "stopped": int(job.stopped)}
		for job in frappe.get_all(
			"Scheduled Job Type",
			filters={"method": ["like", "ai_munimji.%"]},
			fields=["method", "frequency", "cron_format", "stopped"],
		)
	},
	"scheduler_events": sorted(
		e.method
		for e in frappe.get_all(
			"Scheduler Event", filters={"scheduled_against": "AI Munimji Settings"}, fields=["method"]
		)
	),
	"doctypes": sorted(frappe.get_all("DocType", filters={"module": "AI Munimji"}, pluck="name")),
	"telegram_link_table": bool(frappe.db.table_exists("Munimji Telegram Link")),
	"roles": sorted(
		r for r in ("Munimji Viewer", "Munimji Approver", "Munimji Manager") if frappe.db.exists("Role", r)
	),
	"custom_fields": frappe.db.count("Custom Field", {"name": ["like", "%custom_agent_%"]}),
	"notifications": frappe.db.count("Notification", {"name": ["like", "%Munimji%"]}),
	"approval_requests": frappe.db.count("Munimji Approval Request"),
}
with open(args[0], "w", encoding="utf-8") as f:
	json.dump(state, f, indent=1, sort_keys=True)
print(f"state of {state['version']} written to {args[0]}")
