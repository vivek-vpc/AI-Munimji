import frappe

ROLES = ("Munimji Viewer", "Munimji Approver", "Munimji Manager")


def before_install():
	"""Make the roles that the DocTypes' permission rows name. It runs before the DocTypes are synced, which is why it is not after_install."""
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def make_locks():
	"""The rows that serialise work (stores/locks.py) are made here, at install and at every migrate, so that a person's session never has to make one: two sessions that make the
	same row at the same moment deadlock. Running it again changes nothing."""
	from ai_munimji.stores import locks

	locks.ensure()


def make_schedule():
	"""The stock check's scheduled job (schedule.py), at install and at every migrate: it follows what the Settings page holds, so a schedule a person has set survives a migrate, and a
	site that never saved the page gets the job stopped (Watch stock is off by default)."""
	from ai_munimji import schedule

	settings = frappe.get_single("AI Munimji Settings")
	schedule.sync(bool(settings.enabled), settings.check_cron)


NOTIFICATION = "Munimji: a request is waiting for an answer"


def make_notification():
	"""One notification in the Desk bell of the people who answer requests, when a request is made: a Frappe Notification on the New event of the request, to the role Munimji Approver,
	on the System Notification channel only (no e-mail). Frappe runs the New event once, when the record is first inserted, so a request that waits for days and the ticks that
	look at it again make no second one. It is made if it is missing and never overwritten: a site that edited or switched it off keeps its choice. Uninstall removes it."""
	if frappe.db.exists("Notification", NOTIFICATION):
		return
	frappe.get_doc(
		{
			"doctype": "Notification",
			"name": NOTIFICATION,
			"enabled": 1,
			"channel": "System Notification",
			"document_type": "Munimji Approval Request",
			"event": "New",
			"condition": 'doc.status == "pending"',
			"subject": "{{ doc.title }}",
			"message_type": "Markdown",
			"message": "A request is waiting for your answer: {{ doc.title }}.",
			"recipients": [{"receiver_by_role": "Munimji Approver"}],
		}
	).insert(ignore_permissions=True)
