"""Flag the requests and settings changes that the seal already holds, so that the audit sweep reads only what is new.

Before this patch the sweep found what was unsealed by reading every entry of the chain and every closed request. It now asks for the closed requests (and settings changes) whose
`sealed` flag is 0, and the flag is set when the entry is appended. A site that was sealed before the flag existed has the flag at 0 everywhere, so this sets it where the chain holds an
entry. Running it again changes nothing. (If it has not run, the store finds out for itself, 500 at a time, and never seals a record twice: stores/core.py.)
"""

import frappe


def execute():
	frappe.db.sql(
		"""UPDATE `tabMunimji Approval Request` r
		JOIN `tabMunimji Audit Seal` s ON s.source = 'approval' AND s.ref_id = r.name
		SET r.sealed = 1 WHERE r.sealed = 0"""
	)
	frappe.db.sql(
		"""UPDATE `tabMunimji Settings Change` c
		JOIN `tabMunimji Audit Seal` s ON s.source = 'setting' AND s.ref_id = c.name
		SET c.sealed = 1 WHERE c.sealed = 0"""
	)
