# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MunimjiApprovalRequest(Document):
	"""The engine's approval record. Its rows are written and read by the stores in ai_munimji/stores (ApprovalStore); the columns are what the list view and the filters need and the two
	JSON fields hold the request and the answer exactly as the engine made them. Nothing here changes what the engine wrote."""
