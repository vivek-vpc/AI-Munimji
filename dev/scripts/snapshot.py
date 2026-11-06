# Writes a snapshot of what the site holds that this app could have added: the argument is the output file.
#   env SITE=check.localhost bash dev/run-script.sh dev/scripts/snapshot.py /tmp/after-install.json
import json

out = args[0]
db = frappe.db
DOCTYPES = ("Purchase Order", "Material Request", "Stock Entry")
OURS = ("AI Munimji Settings", "Munimji Approval Request", "Munimji Calendar Event")


def names(doctype, **filters):
	return sorted(frappe.get_all(doctype, filters=filters, pluck="name"))


def count(table):
	return db.sql(f"SELECT COUNT(*) FROM `tab{table}`")[0][0]


def columns(doctype):
	return sorted(
		row[0] for row in db.sql(f"SHOW COLUMNS FROM `tab{doctype}`") if row[0].startswith("custom_")
	)


tables = sorted(row[0] for row in db.sql("SHOW TABLES"))
snapshot = {
	"tables": tables,
	"tables_of_the_app": [t for t in tables if "unimji" in t],
	"custom_columns": {dt: columns(dt) for dt in DOCTYPES},
	"indexes_on_the_reference": {
		dt: sorted(
			(i["Key_name"], i["Non_unique"])
			for i in db.sql(f"SHOW INDEX FROM `tab{dt}` WHERE Column_name = 'custom_agent_ref'", as_dict=True)
		)
		for dt in DOCTYPES
	},
	"roles": names("Role", name=["like", "Munimji%"]),
	"has_role_rows": db.sql("SELECT COUNT(*) FROM `tabHas Role` WHERE role LIKE 'Munimji%%'")[0][0],
	"custom_fields": names("Custom Field", dt=["in", list(DOCTYPES)], fieldname=["like", "custom_agent%"]),
	"custom_field_labels": {
		n: frappe.db.get_value("Custom Field", n, "label")
		for n in names("Custom Field", dt=["in", list(DOCTYPES)], fieldname=["like", "custom_agent%"])
	},
	"doctypes_of_the_module": names("DocType", module="AI Munimji"),
	"module_def": names("Module Def", name="AI Munimji"),
	"permission_types": names("Permission Type", doc_type=["like", "Munimji%"]),
	"permission_types_all": names("Permission Type"),
	"docperm_approve_columns": {
		t: db.has_column(t, "approve") for t in ("DocPerm", "Custom DocPerm", "DocShare")
	},
	"custom_fields_for_permission_types": names("Custom Field", fieldname="approve"),
	# by what they are, not by their names: a new record gets a new random name every time the app is installed
	"scheduled_job_types": sorted(
		f"{j.method} | {j.frequency} | {j.cron_format} | stopped={j.stopped}"
		for j in frappe.get_all(
			"Scheduled Job Type",
			filters={"method": ["like", "ai_munimji%"]},
			fields=["method", "frequency", "cron_format", "stopped"],
		)
	),
	"docperm_rows_of_our_doctypes": db.sql(
		"SELECT COUNT(*) FROM `tabDocPerm` WHERE parent IN %(ours)s", {"ours": OURS}
	)[0][0],
	"docperm_rows_of_munimji_roles_elsewhere": db.sql(
		"SELECT COUNT(*) FROM `tabDocPerm` WHERE role LIKE 'Munimji%%' AND parent NOT IN %(ours)s",
		{"ours": OURS},
	)[0][0]
	+ db.sql("SELECT COUNT(*) FROM `tabCustom DocPerm` WHERE role LIKE 'Munimji%%'")[0][0],
	"singles_of_the_app": db.sql("SELECT COUNT(*) FROM tabSingles WHERE doctype = 'AI Munimji Settings'")[0][
		0
	],
	"auth_rows_of_the_app": db.sql("SELECT COUNT(*) FROM `__Auth` WHERE doctype = 'AI Munimji Settings'")[0][
		0
	],
	"versions_of_the_app": db.sql(
		"SELECT COUNT(*) FROM tabVersion WHERE ref_doctype IN %(ours)s", {"ours": OURS}
	)[0][0],
	"property_setters_of_the_app": db.sql(
		"SELECT COUNT(*) FROM `tabProperty Setter` WHERE doc_type IN %(ours)s", {"ours": OURS}
	)[0][0],
	"installed_apps": frappe.get_installed_apps(),
	"counts": {
		t: count(t)
		for t in (
			"DocType",
			"DocField",
			"DocPerm",
			"Custom DocPerm",
			"Custom Field",
			"Property Setter",
			"Role",
			"Has Role",
			"Scheduled Job Type",
			"Module Def",
			"Permission Type",
			"Workspace",
			"Version",
		)
	},
}
with open(out, "w") as f:
	json.dump(snapshot, f, indent=1, sort_keys=True, default=str)
print("snapshot written:", out)
