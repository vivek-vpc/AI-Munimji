# Reads the source of the two ERP clients (no site needed) and lists what each of their methods reads: the DocType, the fields asked for, the fields filtered on.
# Writes reads_rest.json and reads_frappe.json; dev/scripts/check_client_fields.py checks them against a real ERPNext 16 site, and docs/ERP_FIELDS_V16.md is written from the result.
#   python dev/scripts/list_client_reads.py <path of the REST client, erp_agents/core/erp/erpnext.py> <path of ai_munimji/erp_client.py> <output folder>
import ast
import json
import sys
from pathlib import Path


def const(node):
	return node.value if isinstance(node, ast.Constant) else None


def field_names(node):
	if isinstance(node, (ast.List, ast.Tuple)):
		return [const(e) if const(e) is not None else "<computed>" for e in node.elts]
	return ["<computed>"]


def filter_fields(node):
	out = []
	if isinstance(node, (ast.List, ast.Tuple)):
		for e in node.elts:
			if isinstance(e, (ast.List, ast.Tuple)) and e.elts and const(e.elts[0]) is not None:
				out.append(const(e.elts[0]))
			elif isinstance(e, (ast.BinOp, ast.Name)):
				out.append("<computed>")
	elif isinstance(node, ast.BinOp):
		out += filter_fields(node.left) + filter_fields(node.right)
	elif isinstance(node, ast.Name):
		out.append("<computed>")
	return out


def reads(path: Path) -> list[dict]:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	found = []
	for fn in ast.walk(tree):
		if not isinstance(fn, ast.FunctionDef):
			continue
		for node in ast.walk(fn):
			if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
				continue
			kind = node.func.attr
			if kind not in ("_list", "_optional", "_doc"):
				continue
			args = node.args[1:] if kind == "_optional" else node.args  # _optional(what, doctype, fields, filters)
			doctype = const(args[0]) if args else None
			if doctype is None:
				continue
			parent = next((const(k.value) for k in node.keywords if k.arg == "parent"), None)
			found.append(
				{
					"method": fn.name,
					"kind": kind,
					"doctype": doctype,
					"parent": parent,
					"fields": ["*"] if kind == "_doc" else field_names(args[1]) if len(args) > 1 else [],
					"filters": [] if kind == "_doc" else filter_fields(args[2]) if len(args) > 2 else [],
				}
			)
	unique = {json.dumps(r, sort_keys=True): r for r in found}
	return sorted(unique.values(), key=lambda r: (r["method"], r["doctype"], json.dumps(r["fields"])))


if __name__ == "__main__":
	rest, frappe_client, out = (Path(a) for a in sys.argv[1:4])
	out.mkdir(parents=True, exist_ok=True)
	for name, path in (("rest", rest), ("frappe", frappe_client)):
		rows = reads(path)
		(out / f"reads_{name}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
		print(f"{name}: {len(rows)} distinct reads in {path.name}")
