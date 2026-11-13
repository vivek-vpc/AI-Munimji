# Used by dev/check-upgrade.sh, on the site that holds the OLD version of the app: makes the settings a person would have by then (the monitor on, a schedule, a few changed values), so that
# the upgrade has something of theirs to keep. Run through dev/frappe_run.py, as Administrator.
doc = frappe.get_doc("AI Munimji Settings")
doc.enabled = 1
doc.check_cron = "30 7 * * 1"
doc.min_qty = 11
doc.reminder_after_hours = 30
doc.save()
frappe.db.commit()
print(
	f"seeded: enabled {doc.enabled}, check_cron {doc.check_cron}, min_qty {doc.min_qty}, reminder_after_hours {doc.reminder_after_hours}"
)
