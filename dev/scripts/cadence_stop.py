# Ends the scheduler experiment: removes the two probe jobs and the Scheduler Event made by cadence_start.py.
for name in frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ai_munimji.jobs.tick_probe%"]}, pluck="name"):
	frappe.delete_doc("Scheduled Job Type", name, force=1, ignore_permissions=True)
for name in frappe.get_all("Scheduler Event", filters={"method": ["like", "ai_munimji.jobs.tick_probe%"]}, pluck="name"):
	frappe.delete_doc("Scheduler Event", name, force=1, ignore_permissions=True)
print("left:", frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ai_munimji%"]}, fields=["method", "cron_format"]))
