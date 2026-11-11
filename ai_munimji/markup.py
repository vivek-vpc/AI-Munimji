"""The few pieces of HTML the server writes for the Desk (the flow block of a request, the sentence after an answer), and the one rule that keeps them safe: every piece of text goes through `esc`,
so that nothing an item or a supplier is called (it comes from ERPNext, and anyone who may edit an item chooses it) can become markup. The tags are written here and nowhere else.
"""

import html
from urllib.parse import quote

import frappe


def esc(text) -> str:
	"""The text as it must be written inside HTML or inside a quoted attribute: nothing in it is markup."""
	return html.escape("" if text is None else str(text), quote=True)


def form_path(doctype: str, name: str) -> str:
	"""Where the Desk shows this document (a path on the site, so that it holds behind any address the site is reached by)."""
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}/{quote(str(name), safe='')}"


def list_path(doctype: str) -> str:
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}"


def link(path: str, label: str) -> str:
	return f'<a href="{esc(path)}">{esc(label)}</a>'
