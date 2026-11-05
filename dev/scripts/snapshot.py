# Writes a snapshot of what the site holds that this app could have added: the argument is the output file.
#   env SITE=check.localhost bash dev/run-script.sh dev/scripts/snapshot.py /tmp/after-install.json
import json

out = args[0]
db = frappe.db


def names(doctype, **filters):
	return sorted(frappe.get_all(doctype, filters=filters, pluck="name"))


def count(table):
	return db.sql(f"SELECT COUNT(*) FROM `tab{table}`")[0][0]


tables = sorted(row[0] for row in db.sql("SHOW TABLES"))
snapshot = {
	"tables": tables,
	"tables_of_the_app": [t for t in tables if "unimji" in t],
	"purchase_order_columns": sorted(row[0] for row in db.sql("SHOW COLUMNS FROM `tabPurchase Order`") if row[0].startswith("custom_")),
	"roles": names("Role", name=["like", "Munimji%"]),
	"has_role_rows": db.sql("SELECT COUNT(*) FROM `tabHas Role` WHERE role LIKE 'Munimji%%'")[0][0],
	"custom_fields": names("Custom Field", dt="Purchase Order", fieldname=["like", "custom_agent%"]),
	"doctypes_of_the_module": names("DocType", module="AI Munimji"),
	"module_def": names("Module Def", name="AI Munimji"),
	"permission_types": names("Permission Type", doc_type=["like", "Munimji%"]),
	"permission_types_all": names("Permission Type"),
	"docperm_approve_columns": {t: db.has_column(t, "approve") for t in ("DocPerm", "Custom DocPerm", "DocShare")},
	"custom_fields_for_permission_types": names("Custom Field", fieldname="approve"),
	"scheduled_job_types": names("Scheduled Job Type", method=["like", "ai_munimji%"]),
	"docperm_rows_of_our_doctypes": db.sql("SELECT COUNT(*) FROM `tabDocPerm` WHERE parent IN ('Munimji Approval Request','AI Munimji Settings')")[0][0],
	"singles_of_the_app": db.sql("SELECT COUNT(*) FROM tabSingles WHERE doctype = 'AI Munimji Settings'")[0][0],
	"auth_rows_of_the_app": db.sql("SELECT COUNT(*) FROM `__Auth` WHERE doctype = 'AI Munimji Settings'")[0][0],
	"versions_of_the_app": db.sql("SELECT COUNT(*) FROM tabVersion WHERE ref_doctype IN ('Munimji Approval Request','AI Munimji Settings')")[0][0],
	"installed_apps": frappe.get_installed_apps(),
	"counts": {t: count(t) for t in ("DocType", "DocField", "DocPerm", "Custom DocPerm", "Custom Field", "Property Setter", "Role", "Has Role", "Scheduled Job Type", "Module Def", "Permission Type", "Workspace", "Version")},
}
with open(out, "w") as f:
	json.dump(snapshot, f, indent=1, sort_keys=True, default=str)
print("snapshot written:", out)
