from ai_munimji import custom_fields

app_name = "ai_munimji"
app_title = "AI Munimji"
app_publisher = "AI Munimji project"
app_description = "Watches stock and prepares draft purchase orders for approval"
app_email = "vivek.vpc1985@gmail.com"
app_license = "GPL-3.0-or-later"

# Only the hooks this app uses are here. The template's list of the others is in Frappe's documentation ("Hooks").

# Apps
# ------------------

required_apps = ["erpnext"]

# Installation
# ------------

# the roles must exist before the DocTypes are synced (their permission rows name them), so they are made before the install
before_install = "ai_munimji.install.before_install"

# after the DocTypes are synced, at install and at every migrate: the rows that serialise work (stores/locks.py), the stock check's scheduled job (schedule.py, which follows the
# Settings page) and the notification to the people who answer requests; each one finds what is already there and changes nothing. The last one only SAYS, and stops nothing, if the
# database has innodb_snapshot_isolation ON (dbcheck.py).
after_install = [
	"ai_munimji.install.make_locks",
	"ai_munimji.install.make_schedule",
	"ai_munimji.install.make_notification",
	"ai_munimji.install.check_database",
]
after_migrate = [
	"ai_munimji.install.make_locks",
	"ai_munimji.install.make_schedule",
	"ai_munimji.install.make_notification",
	"ai_munimji.install.check_database",
]

# the seven fields this app adds to Purchase Order, Material Request and Stock Entry (ai_munimji/custom_fields.py), written by `bench export-fixtures --app ai_munimji`
# and filtered by name so that no other Custom Field of the site is exported with them
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["name", "in", list(custom_fields.NAMES)]],
	}
]

# The Desk (Frappe 16)
# --------------------

# The app's tile on the apps screen. The rail behind it, the module's sidebar and the home page are shipped as files: ai_munimji/dock/ai_munimji/, ai_munimji/ai_munimji/sidebar/
# and ai_munimji/ai_munimji/workspace/ (tests/test_desk.py checks that they agree). Only people with one of the app's roles see the tile. The logo is set here and NOT through
# app_logo_url, which the last app to set it would take over for the whole navbar.
add_to_apps_screen = [
	{
		"name": "ai_munimji",
		"logo": "/assets/ai_munimji/images/ai-munimji-logo.png",
		"title": "AI Munimji",
		"route": "/desk/ai-munimji",
		"has_permission": "ai_munimji.permissions.check_app_permission",
	}
]

# Uninstallation
# ------------

# removes what the install added outside the app's own DocTypes and says what stays (docs/UNINSTALL.md)
before_uninstall = "ai_munimji.uninstall.before_uninstall"

# Permissions
# -----------

# A controller hook can only DENY (frappe/permissions.py: has_controller_permissions). It is called with the keywords doc, ptype, user, debug.
has_permission = {
	"Munimji Approval Request": "ai_munimji.permissions.has_permission",
	"Munimji Telegram Link": "ai_munimji.permissions.link_has_permission",
}
permission_query_conditions = {
	"Munimji Telegram Link": "ai_munimji.permissions.link_query_conditions",
}

# A user who is deleted takes their Telegram link with them (their chat id is personal data).
doc_events = {
	"User": {"on_trash": "ai_munimji.telegram.links.on_user_trash"},
}

# Deleting
# --------

# The app's records name an Item, a Warehouse, a Supplier, a Purchase Order or a Stock Entry in Link fields, but they are history: they keep the name as text and must never stop
# ERPNext from deleting its own documents (Frappe v16: delete_doc.py skips the links of these DocTypes). The AI Munimji Settings page is not in the list: a fallback supplier that
# is still named there is not deleted. tests/test_deleting.py checks the list against the DocTypes the app has.
ignore_links_on_delete = [
	"Munimji Agent Run",
	"Munimji Agent Task",
	"Munimji Approval Delivery",
	"Munimji Approval Request",
	"Munimji Assistant Answer",
	"Munimji Audit Seal",
	"Munimji Calendar Event",
	"Munimji Chat Log",
	"Munimji Count Review",
	"Munimji Cycle Count",
	"Munimji Delivery Chase",
	"Munimji Inbound Seen",
	"Munimji Job Run",
	"Munimji Lock",
	"Munimji Purchase Proposal",
	"Munimji Quote Round",
	"Munimji Receipt Check",
	"Munimji Settings Change",
	"Munimji Settings Override",
	"Munimji Stock Alert",
	"Munimji Stock Notice",
	"Munimji Stock Transfer",
	"Munimji Telegram Link",
	"Munimji Tool Call",
	"Munimji Vendor Message",
	"Munimji Vendor Reply",
	"Munimji Work Order",
]

# Scheduled Tasks
# ---------------

# None are declared here on purpose. Frappe resets or deletes at every migrate the job types that hooks declare or leave undeclared, so the stock check's own job (a Scheduler Event
# and the Scheduled Job Type linked to it, which the AI Munimji Settings page switches on and off and sets the time of) is made by install.py and kept in step by schedule.py.
