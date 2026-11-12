# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MunimjiTelegramLink(Document):
	"""Which Telegram chat is this person's (telegram/links.py makes it, when the person presses Start on their Connect Telegram link). A person may switch it off or delete it; nobody types a chat id."""

	def validate(self):
		if not str(self.chat_id or "").isdigit():
			frappe.throw(
				_(
					"A Telegram chat is a person's own chat number (digits only); group and channel chats are not supported."
				)
			)

	def on_trash(self):
		from ai_munimji.telegram import links

		links.forget_open_code(self.user)  # a code the person made and never used stops working with the link
