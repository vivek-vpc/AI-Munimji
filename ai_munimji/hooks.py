from ai_munimji import custom_fields

app_name = "ai_munimji"
app_title = "AI Munimji"
app_publisher = "AI Munimji project"
app_description = "Stock monitoring and purchase requests for ERPNext. In development, not released."
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

# the rows that serialise work (stores/locks.py) exist after the DocTypes are synced, at install and at every migrate
after_install = "ai_munimji.install.make_locks"
after_migrate = "ai_munimji.install.make_locks"

# the seven fields this app adds to Purchase Order, Material Request and Stock Entry (ai_munimji/custom_fields.py), written by `bench export-fixtures --app ai_munimji`
# and filtered by name so that no other Custom Field of the site is exported with them
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["name", "in", list(custom_fields.NAMES)]],
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
}

# Scheduled Tasks
# ---------------

# PLACEHOLDER, replaced in Phase 5 (ai_munimji/jobs.py).
# Frappe runs scheduled work at its scheduler tick (240 seconds unless the bench sets another), so nothing here can run more often than that.
scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"ai_munimji.jobs.check_stock",
		],
	},
}
