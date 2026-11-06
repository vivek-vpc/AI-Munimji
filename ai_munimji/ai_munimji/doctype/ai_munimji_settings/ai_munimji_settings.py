# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIMunimjiSettings(Document):
	def validate(self):
		# imported here: the DocType must still load (migrate, uninstall) in a bench from which the engine has been removed
		from ai_munimji import settings_map

		settings_map.validate(self)
