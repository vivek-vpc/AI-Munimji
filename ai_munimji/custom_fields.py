"""The fields this app adds to ERPNext's documents, and the one place that says which they are.

They are the SAME fields, with the same names and types and the same settings, as the ones `erp-agents erp-setup` makes for the standalone service (erpnext-ai-agents,
src/erp_agents/core/erp/erpnext.py, `ERPNextClient.CUSTOM_FIELDS`, at the commit named in docs/NAMES.md), so that an order made by either product is recognised by the other: each
product finds an earlier order of a request by `custom_agent_ref`, and refuses to change or cancel an order that does not carry the right reference. Only the labels and the
descriptions are this app's own words. tests/test_custom_fields.py holds a copy of the service's table and fails if the two differ.

The fixture file (fixtures/custom_field.json) is what `bench export-fixtures --app ai_munimji` writes for these names; hooks.py filters on NAMES, and uninstall.py removes NAMES.
No Python is imported here that needs Frappe: hooks.py imports this module.
"""

from typing import NamedTuple


class CustomField(NamedTuple):
	dt: str  # the DocType the field is added to
	fieldname: str
	fieldtype: str
	label: str
	insert_after: str
	search_index: int  # an index on the reference, because both products look an order up by it
	description: str

	@property
	def name(self) -> str:
		return f"{self.dt}-{self.fieldname}"


REF = "custom_agent_ref"  # the request this document was made from
APPROVED_BY = "custom_agent_approved_by"  # who approved it, and from where: "priya@example.com via desk"
NOTE = "custom_agent_note"  # the recommendation, for the buyer

FIELDS = (
	CustomField("Purchase Order", REF, "Data", "Munimji request", "supplier_name", 1, "Set by AI Munimji when a request is turned into this order. Do not edit."),
	CustomField("Purchase Order", APPROVED_BY, "Data", "Approved by (Munimji)", REF, 0, "Who approved the request, and where from. Do not edit."),
	CustomField("Material Request", REF, "Data", "Munimji request", "company", 1, "Set by AI Munimji when a request is turned into this purchase requisition. Do not edit."),
	CustomField("Material Request", APPROVED_BY, "Data", "Approved by (Munimji)", REF, 0, "Who approved the request, and where from. Do not edit."),
	CustomField("Material Request", NOTE, "Small Text", "Munimji note", APPROVED_BY, 0, "AI Munimji's recommendation (supplier, price, delivery) for the buyer. Do not edit."),
	CustomField("Stock Entry", REF, "Data", "Munimji request", "company", 1, "Set by AI Munimji when a request is turned into this stock transfer. Do not edit."),
	CustomField("Stock Entry", APPROVED_BY, "Data", "Approved by (Munimji)", REF, 0, "Who approved the request, and where from. Do not edit."),
)
NAMES = tuple(f.name for f in FIELDS)
DOCTYPES = tuple(dict.fromkeys(f.dt for f in FIELDS))

# What the standalone service sets on every one of them (`body` in ERPNextClient.ensure_po_reference_field).
FLAGS = {"read_only": 1, "no_copy": 1, "print_hide": 1}
