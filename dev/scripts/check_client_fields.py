# Checks what the two ERP clients read (dev/scripts/list_client_reads.py) against the DocTypes of the site this script runs on, and prints a report: fields that do not exist,
# and what one client reads that the other does not. docs/ERP_FIELDS_V16.md is written from this output.
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/check_client_fields.py <folder with reads_rest.json and reads_frappe.json>
import json
import re
from pathlib import Path

import frappe
from ai_munimji_engine.packs.stock_procurement.erp import STOCK_COLUMNS

folder = Path(
	args[0] if args else "dev/tmp_reads"
)  # the folder list_client_reads.py wrote, as seen from where this runs
STANDARD = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"idx",
	"parent",
	"parentfield",
	"parenttype",
}
reads = {n: json.loads((folder / f"reads_{n}.json").read_text(encoding="utf-8")) for n in ("rest", "frappe")}


def plain(field: str) -> list[str]:
	"""The column names inside a field expression: `item_code`, `MIN(posting_date) as first_date` -> posting_date, `SUM(actual_qty) as qty` -> actual_qty."""
	m = re.match(r"^\s*\w+\((\w+)\)\s*(?:as\s+\w+)?\s*$", field, re.I)
	return [m.group(1)] if m else [field]


def exists(doctype: str, field: str) -> bool:
	if field in STANDARD or field in ("*", "<computed>"):
		return True
	return frappe.get_meta(doctype).has_field(field)


print(f"ERPNext {frappe.get_attr('erpnext.__version__')}, Frappe {frappe.__version__}\n")
missing = []
for client, rows in reads.items():
	for r in rows:
		for field in [x for f in r["fields"] for x in plain(f)] + r["filters"]:
			if not exists(r["doctype"], field):
				missing.append((client, r["method"], r["doctype"], field))
print(
	"Fields that do not exist on this site:"
	if missing
	else "Every field either client reads exists on this site (the ones built at run time are listed below)."
)
for m in missing:
	print("  ", m)

bin_columns = [c for c in STOCK_COLUMNS if c != "item_code"]
print("\nBin columns the Frappe client asks for (the engine's STOCK_COLUMNS, those this site has):")
print(
	"  ",
	[c for c in STOCK_COLUMNS if exists("Bin", c)],
	"| missing:",
	[c for c in STOCK_COLUMNS if not exists("Bin", c)],
)


def sets(client: str) -> set[tuple[str, str]]:
	out = set()
	for r in reads[client]:
		for f in r["fields"] + r["filters"]:
			if f in ("<computed>", "*"):
				continue
			for x in plain(f):
				out.add(((r["parent"] and f"{r['doctype']} (of {r['parent']})") or r["doctype"], x))
	return out


rest, mine = sets("rest"), sets("frappe")
print("\nRead by the REST client only (DocType, field):")
for item in sorted(rest - mine):
	print("  ", item)
print("\nRead by the Frappe client only:")
for item in sorted(mine - rest):
	print("  ", item)
whole = {(c, r["doctype"]) for c in reads for r in reads[c] if r["kind"] == "_doc"}
print("\nWhole documents read (get_doc / REST resource):")
for item in sorted(whole):
	print("  ", item)
