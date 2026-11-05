# Prints what the app has put on the site: scheduled job types, the unique index on Purchase Order, roles, permission rows.
# Run with:  .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/inspect_site.py
print("scheduled job types:", frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ai_munimji%"]}, fields=["method", "frequency", "cron_format", "stopped"]))
print("indexes on custom_agent_ref:", frappe.db.sql("SHOW INDEX FROM `tabPurchase Order` WHERE Column_name = 'custom_agent_ref'", as_dict=True))
column = frappe.db.sql("SHOW COLUMNS FROM `tabPurchase Order` WHERE Field = 'custom_agent_ref'", as_dict=True)
print("column:", column)
print("roles:", frappe.get_all("Role", filters={"name": ["like", "Munimji%"]}, pluck="name"))
print("existing POs and their custom_agent_ref values:", frappe.db.sql("SELECT name, custom_agent_ref IS NULL AS is_null, custom_agent_ref FROM `tabPurchase Order` LIMIT 5", as_dict=True))
print("permission types:", frappe.get_all("Permission Type", pluck="name"))
print("DocPerm approve column:", frappe.db.has_column("DocPerm", "approve"), "| Custom DocPerm:", frappe.db.has_column("Custom DocPerm", "approve"), "| DocShare:", frappe.db.has_column("DocShare", "approve"))
