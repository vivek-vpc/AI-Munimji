"""Gets a site ready for the browser check of the Telegram screens (dev/browser/telegram-ui.cjs), and puts it back:

    ... telegram_ui_setup.py            makes a Munimji Manager and a Munimji Approver (password Munimji-dev-1!), switches Telegram on with a pretend token, leaves the bot unconnected
    ... telegram_ui_setup.py teardown   removes them, their Telegram links, and switches Telegram off

Development tooling for a throw-away site (its name starts with "world"): it is not part of the app. dev/telegram-e2e.ps1 -Browser runs it.
"""

import sys

PASSWORD = "Munimji-dev-1!"
TOKEN = "424242:AAE2E-pretend-token-not-a-secret"
PEOPLE = {
	"ui.manager@example.com": ("Munimji Manager", "Purchase User", "Stock User"),
	"ui.alice@example.com": ("Munimji Approver", "Purchase User", "Purchase Manager", "Stock User"),
	"ui.viewer@example.com": ("Munimji Viewer",),
}

assert frappe.local.site.startswith("world"), f"{frappe.local.site} is not a throw-away site"
frappe.set_user("Administrator")


def set_page(**values) -> None:
	page = frappe.get_doc("AI Munimji Settings")
	for key, value in values.items():
		page.set(key, value)
	page.save()
	frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")


for email in PEOPLE:
	frappe.db.delete("Munimji Telegram Link", {"user": email})
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)

if "teardown" in args:
	set_page(telegram_enabled=0, telegram_bot_username="")
	print("removed the people and switched Telegram off")
else:
	for email, roles in PEOPLE.items():
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		)
		user.flags.ignore_password_policy = True
		user.new_password = PASSWORD
		user.insert(ignore_permissions=True)
	set_page(telegram_enabled=1, telegram_bot_token=TOKEN, telegram_mode="Webhook", telegram_bot_username="")
	print("made", ", ".join(PEOPLE), "and switched Telegram on (the bot is not connected yet)")
