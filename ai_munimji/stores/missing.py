import frappe


def not_there() -> None:
	"""A record that is not there is an answer, not a problem. When Frappe is asked for one it says so twice: by raising DoesNotExistError, which the stores catch, and by putting "<DocType> <name> not
	found" among the messages that the person's browser shows with the reply. The second would pop up on the screen of whoever answered a request ("Munimji Settings Override ... not found", five times,
	after pressing Approve), so the store takes it back. Call it from the `except frappe.DoesNotExistError` that turns the absence into a return value."""
	log = frappe.local.message_log
	if log and "not found" in str(log[-1]):
		log.pop()
