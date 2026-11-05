# Probe on the TEST site: why did the test see no Version record? (run with the site name as the first argument of run-script.sh's site: see below)
print("site:", frappe.local.site, "| track_changes:", frappe.get_meta("AI Munimji Settings").track_changes)
settings = frappe.get_doc("AI Munimji Settings")
settings.stock_threshold = (settings.stock_threshold or 0) + 1
settings.save()
print("versions:", frappe.get_all("Version", filters={"ref_doctype": "AI Munimji Settings"}, pluck="data"))
frappe.db.rollback()
