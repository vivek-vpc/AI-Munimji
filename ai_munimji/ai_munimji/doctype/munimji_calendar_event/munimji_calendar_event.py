# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MunimjiCalendarEvent(Document):
	"""One row of the demand calendar on AI Munimji Settings. The rules for a row (dates in order, the change in use) are the engine's; see ai_munimji/settings_map.py."""

	pass
