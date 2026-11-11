"""Writes the DocType files of the engine's stores from ai_munimji/stores/specs.py, the one place that says what each DocType holds (Phase 4b).

    python dev/scripts/make_doctypes.py            # write the files that differ
    python dev/scripts/make_doctypes.py --check    # change nothing; exit 1 and name the files that would change (tests/test_store_specs.py does the same in the bench)

It runs outside a bench (it reads specs.py by path and imports nothing of Frappe). For each table it writes `<snake>/<snake>.json` and, only if there is none, `__init__.py` and a controller
that does nothing; a controller written by hand is never touched. It also writes the table of DocTypes into docs/STORES.md, between its two marker lines. `modified` is the old file's plus one second when anything else in the file changed, so that `bench migrate` takes a
changed file and a rerun with no change writes nothing.
"""

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCTYPES = ROOT / "ai_munimji" / "ai_munimji" / "doctype"
FIRST = "2026-11-07 12:00:00.000000"
APPROVAL = "Munimji Approval Request"
BORN = {
	"Munimji Approval Request": "2026-11-05 17:47:10.827362"
}  # the placeholder's own creation time; the others are new

spec = importlib.util.spec_from_file_location(
	"munimji_store_specs", ROOT / "ai_munimji" / "stores" / "specs.py"
)
specs = importlib.util.module_from_spec(spec)
sys.modules["munimji_store_specs"] = specs
spec.loader.exec_module(specs)

FIELDTYPE = {
	"data": "Data",
	"text": "Small Text",
	"long": "Long Text",
	"json": "JSON",
	"int": "Int",
	"float": "Float",
	"check": "Check",
	"datetime": "Datetime",
	"date": "Date",
}
NO = dict.fromkeys(("read", "write", "create", "delete", "email", "print", "report", "export", "share"), 0)


def snake(doctype: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", doctype.lower()).strip("_")


def class_name(doctype: str) -> str:
	return "".join(part.capitalize() for part in doctype.split())


def field(col, table) -> dict:
	out = {
		"fieldname": col.name,
		"fieldtype": "Link" if col.link else FIELDTYPE[col.kind],
		"label": col.title,
		"read_only": 1,
	}
	if col.link:
		out["options"] = col.link
	for letter, key in (
		("l", "in_list_view"),
		("f", "in_standard_filter"),
		("i", "search_index"),
		("u", "unique"),
		("h", "hidden"),
	):
		if letter in col.flags:
			out[key] = 1
	if col.kind == "float":
		out["precision"] = ""
	return out


def fields_of(table) -> list[dict]:
	out = []
	if table.doctype == APPROVAL:
		# the form's first thing is the request in words, drawn from the stored JSON by the form's script (munimji_approval_request.js); the columns come after it
		out.append({"fieldname": "reasoning", "fieldtype": "HTML", "label": "Why this request"})
	if table.numbered:
		out.append(
			{
				"fieldname": table.key[0],
				"fieldtype": "Int",
				"label": "Number",
				"read_only": 1,
				"unique": 1,
				"in_list_view": 1,
			}
		)
	details_started = False
	for col in table.cols:
		if col.kind in ("json", "long") and not details_started and out:
			section = {"fieldname": "details_section", "fieldtype": "Section Break", "label": "Details"}
			if table.doctype == APPROVAL:
				section.update(
					label="The request and the answer, exactly as the engine kept them", collapsible=1
				)
			out.append(section)
			details_started = True
		out.append(field(col, table))
	if any(c.null for c in table.cols):
		out.append(
			{"fieldname": "nulls", "fieldtype": "JSON", "label": "Empty numbers", "hidden": 1, "read_only": 1}
		)
	if table.json_row:
		out.append(
			{
				"fieldname": "row_json",
				"fieldtype": "JSON",
				"label": "The row, as the engine kept it",
				"read_only": 1,
			}
		)
	for f in out:
		if f.get("precision") == "":
			del f["precision"]
	return out


def permissions_of(table) -> list[dict]:
	rows = []
	for role, letters in table.perms.items():
		row = {"role": role, **NO}
		for letter, keys in (
			("r", ("read",)),
			("w", ("write",)),
			("c", ("create",)),
			("d", ("delete",)),
			("x", ("report", "export")),
		):
			if letter in letters:
				for key in keys:
					row[key] = 1
		if "a" in letters:
			row["approve"] = 1
		rows.append(dict(sorted(row.items())))
	return rows


def render(table, modified: str) -> dict:
	fields = fields_of(table)
	doc = {
		"actions": [],
		"allow_rename": 0,
		"autoname": "Prompt",
		"creation": BORN.get(table.doctype, FIRST),
		"doctype": "DocType",
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields],
		"fields": fields,
		"in_create": 1,
		"index_web_pages_for_search": 0,
		"links": [],
		"modified": modified,
		"modified_by": "Administrator",
		"module": "AI Munimji",
		"name": table.doctype,
		"naming_rule": "Set by user",
		"owner": "Administrator",
		"permissions": permissions_of(table),
		"row_format": "Dynamic",
		"sort_field": "creation",
		"sort_order": "DESC",
		"states": [],
		"track_changes": 0,
	}
	if table.title_field:
		doc["title_field"] = table.title_field
	return doc


def text_of(doc: dict) -> str:
	return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def stamp(previous: str) -> str:
	return (datetime.strptime(previous, "%Y-%m-%d %H:%M:%S.%f") + timedelta(seconds=1)).strftime(
		"%Y-%m-%d %H:%M:%S.%f"
	)


def files() -> dict[Path, str]:
	"""Every file this script owns and what it should say."""
	out = {}
	for table in specs.TABLES:
		name = snake(table.doctype)
		path = DOCTYPES / name / f"{name}.json"
		modified = FIRST
		if path.exists():
			old = json.loads(path.read_text(encoding="utf-8"))
			modified = old.get("modified", FIRST)
			if {k: v for k, v in old.items() if k != "modified"} != {
				k: v for k, v in render(table, modified).items() if k != "modified"
			}:
				modified = stamp(modified)
		out[path] = text_of(render(table, modified))
	return out


SHORT = {"Munimji Viewer": "V", "Munimji Approver": "A", "Munimji Manager": "M", "System Manager": "S"}
BEGIN, END = "<!-- stores-table:begin -->", "<!-- stores-table:end -->"


def doc_table() -> str:
	"""The table of docs/STORES.md: one row per DocType, from the same specs the files are made from."""
	lines = [
		"| DocType | Engine table | Kept | Columns (derived ones in round brackets, the app's own in square brackets) | JSON | Rights | For a person's screen |",
		"|---|---|---|---|---|---|---|",
	]
	for table in specs.TABLES:
		columns = [
			f"({c.name})" if c.derived else f"[{c.name}]" if c.internal else c.name
			for c in table.cols
			if c.kind != "json"
		]
		if table.numbered:
			columns.insert(0, table.key[0])
		jsons = [c.name for c in table.cols if c.kind == "json"] or ["none"]
		if table.json_row:
			jsons = ["the whole row (`row_json`)"]
		rights = (
			"; ".join(f"{SHORT.get(role, role)} {letters}" for role, letters in table.perms.items())
			or "none (Administrator only)"
		)
		kept = "json row" if table.json_row else "columns"
		lines.append(
			f"| {table.doctype} | `{table.engine}` | {kept} | {', '.join(columns)} | {', '.join(jsons)} | {rights} | {'yes' if table.person else 'no'} |"
		)
	return "\n".join(lines)


def stores_doc() -> tuple[Path, str]:
	path = ROOT / "docs" / "STORES.md"
	text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
	head, rest = text.split(BEGIN, 1)
	_old, tail = rest.split(END, 1)
	return path, f"{head}{BEGIN}\n{doc_table()}\n{END}{tail}"


def stub(table, module: str, base: str) -> str:
	return (
		"# Copyright (c) 2026, AI Munimji project and contributors\n# For license information, please see license.txt\n\n"
		f"from {module} import {base}\n\n\nclass {class_name(table.doctype)}({base}):\n\tpass\n"
	)


def controllers() -> dict[Path, str]:
	"""A controller is written when there is none, and an old default one (a bare Document) is replaced by the current default (a StoreRecord); one written by hand is left as it is."""
	out = {}
	for table in specs.TABLES:
		name = snake(table.doctype)
		out[DOCTYPES / name / "__init__.py"] = ""
		path = DOCTYPES / name / f"{name}.py"
		current = stub(table, "ai_munimji.stores.record", "StoreRecord")
		old = stub(table, "frappe.model.document", "Document")
		have = path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.exists() else None
		out[path] = current if have in (None, old) else have
	return out


def main() -> int:
	check = "--check" in sys.argv
	changed = []
	for path, text in files().items():
		if not path.exists() or path.read_text(encoding="utf-8") != text:
			changed.append(path)
			if not check:
				path.parent.mkdir(parents=True, exist_ok=True)
				path.write_text(text, encoding="utf-8", newline="\n")
	for path, text in controllers().items():
		if not path.exists() or path.read_text(encoding="utf-8") != text:
			changed.append(path)
			if not check:
				path.parent.mkdir(parents=True, exist_ok=True)
				path.write_text(text, encoding="utf-8", newline="\n")
	path, text = stores_doc()
	if path.read_bytes().decode("utf-8").replace("\r\n", "\n") != text:
		changed.append(path)
		if not check:
			path.write_text(text, encoding="utf-8", newline="\n")
	for path in changed:
		print(("would write " if check else "wrote ") + str(path.relative_to(ROOT)))
	print(f"{len(specs.TABLES)} DocTypes, {len(changed)} file(s) {'would change' if check else 'written'}")
	return 1 if (check and changed) else 0


if __name__ == "__main__":
	sys.exit(main())
