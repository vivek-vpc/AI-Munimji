"""Two rules about reading and acting, enforced on the source of the app (no site needed, it runs in a second):

1. `frappe.get_all` ignores permissions. It is allowed in the scheduled job module only, which runs as the system on purpose. Everywhere else a read goes through `frappe.get_list`, or
   through a document whose permission was checked.
2. Every method that a browser or an API client can call (`@frappe.whitelist`) checks the caller's permission as its FIRST statement, and none is open to guests.

If this fails, the code does not satisfy the rules the app is built to; fix the code, not the test. An exception is a decision: add the module to SCHEDULED_JOB_MODULES with the reason.
"""

import ast
import unittest

from ai_munimji.tests import scan

# Modules that run as the system, started by the scheduler and by nobody's request. Phase 5 replaces jobs.py; its successor is listed here when it exists.
SCHEDULED_JOB_MODULES = {"ai_munimji/jobs.py"}


def _frappe(node: ast.AST) -> bool:
	return isinstance(node, ast.Name) and node.id == "frappe"


def _is_get_all(call: ast.Call) -> bool:
	f = call.func
	if isinstance(f, ast.Attribute) and f.attr == "get_all":
		return _frappe(f.value) or (
			isinstance(f.value, ast.Attribute) and f.value.attr == "db" and _frappe(f.value.value)
		)  # frappe.get_all, frappe.db.get_all
	return isinstance(f, ast.Name) and f.id == "get_all"


def _whitelist_call(decorator: ast.AST) -> ast.Call | None:
	"""The decorator as a call if it is @frappe.whitelist or @frappe.whitelist(...), else None; a bare @frappe.whitelist is returned as a call without arguments."""
	target = decorator.func if isinstance(decorator, ast.Call) else decorator
	if isinstance(target, ast.Attribute) and target.attr == "whitelist" and _frappe(target.value):
		return decorator if isinstance(decorator, ast.Call) else ast.Call(func=target, args=[], keywords=[])
	return None


def _true(node: ast.AST) -> bool:
	return isinstance(node, ast.Constant) and node.value is True


def _checks_permission(statement: ast.stmt) -> bool:
	"""Is the statement a call that checks the caller's permission and raises if it is missing?"""
	if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)):
		return False
	call = statement.value
	f = call.func
	if not isinstance(f, ast.Attribute):
		return False
	if (
		f.attr == "check_permission"
	):  # self.check_permission("approve"), frappe.get_doc(...).check_permission("read")
		return True
	if _frappe(f.value) and f.attr == "only_for":
		return True
	if _frappe(f.value) and f.attr == "has_permission":
		return any(k.arg == "throw" and _true(k.value) for k in call.keywords)
	return (
		isinstance(f.value, ast.Attribute)
		and _frappe(f.value.value)
		and f.value.attr == "permissions"
		and f.attr.startswith("check_")
	)  # frappe.permissions.check_doctype_permission


class Found:
	def __init__(self):
		self.problems: list[str] = []
		self.whitelisted: list[str] = []
		self.get_all_calls = 0


def scan_source(source: str, filename: str) -> Found:
	found = Found()
	tree = ast.parse(source, filename)
	for node in ast.walk(tree):
		if isinstance(node, ast.Call) and _is_get_all(node):
			found.get_all_calls += 1
			if filename not in SCHEDULED_JOB_MODULES:
				found.problems.append(
					f"{filename}:{node.lineno}: get_all ignores permissions and is allowed only in {sorted(SCHEDULED_JOB_MODULES)}"
				)
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			for decorator in node.decorator_list:
				call = _whitelist_call(decorator)
				if call is None:
					continue
				found.whitelisted.append(node.name)
				for keyword in call.keywords:
					if keyword.arg == "allow_guest" and not (
						isinstance(keyword.value, ast.Constant) and keyword.value.value is False
					):
						found.problems.append(
							f"{filename}:{node.lineno}: {node.name} is open to guests (allow_guest)"
						)
				body = list(node.body)
				if (
					body
					and isinstance(body[0], ast.Expr)
					and isinstance(body[0].value, ast.Constant)
					and isinstance(body[0].value.value, str)
				):
					body = body[1:]  # the docstring
				if not body or not _checks_permission(body[0]):
					found.problems.append(
						f"{filename}:{node.lineno}: {node.name} is whitelisted but does not check the caller's permission as its first statement"
					)
	return found


class TestTheReadsRule(unittest.TestCase):
	def test_the_app_follows_both_rules(self):
		problems, whitelisted, get_all_in_jobs = [], [], 0
		for path in scan.python_files():
			name = scan.relative(path)
			found = scan_source(path.read_text(encoding="utf-8"), name)
			problems += found.problems
			whitelisted += found.whitelisted
			if name in SCHEDULED_JOB_MODULES:
				get_all_in_jobs += found.get_all_calls
		self.assertEqual(problems, [])
		# positive controls: the scan sees what it is meant to see, so that it cannot pass by looking at nothing
		self.assertIn("create_draft_purchase_order", whitelisted)
		self.assertGreaterEqual(
			get_all_in_jobs, 1, "the scheduled job reads with get_all, and the scan sees it"
		)
		for module in SCHEDULED_JOB_MODULES:
			self.assertTrue(
				(scan.ROOT / module).exists(),
				f"{module} is listed as a scheduled job module but does not exist",
			)

	def test_the_scan_notices_get_all_outside_the_job_module(self):
		for source in (
			"import frappe\nrows = frappe.get_all('Item')\n",
			"import frappe\nrows = frappe.db.get_all('Item')\n",
			"from frappe import get_all\nrows = get_all('Item')\n",
		):
			self.assertEqual(len(scan_source(source, "ai_munimji/api.py").problems), 1, source)
			self.assertEqual(
				scan_source(source, "ai_munimji/jobs.py").problems,
				[],
				"the same code is fine in the job module",
			)
		self.assertEqual(
			scan_source("import frappe\nrows = frappe.get_list('Item')\n", "ai_munimji/api.py").problems,
			[],
			"get_list applies permissions",
		)

	def test_the_scan_notices_a_whitelisted_method_without_a_permission_check(self):
		unchecked = (
			"import frappe\n@frappe.whitelist()\ndef f():\n\treturn 1\n",
			"import frappe\n@frappe.whitelist\ndef f():\n\treturn 1\n",
			"import frappe\n@frappe.whitelist(methods=['POST'])\ndef f():\n\tx = 1\n\tfrappe.has_permission('Item', 'read', throw=True)\n",  # not the first statement
			"import frappe\n@frappe.whitelist()\ndef f():\n\tfrappe.has_permission('Item', 'read')\n",  # asks, but does not raise
			"import frappe\n@frappe.whitelist(allow_guest=True)\ndef f():\n\tfrappe.only_for('System Manager')\n",  # checked, but open to guests
			"import frappe\nclass A:\n\t@frappe.whitelist()\n\tdef f(self):\n\t\t'''doc'''\n\t\treturn 1\n",
		)
		for source in unchecked:
			self.assertTrue(scan_source(source, "ai_munimji/api.py").problems, source)
		checked = (
			"import frappe\n@frappe.whitelist()\ndef f():\n\tfrappe.only_for('System Manager')\n\treturn 1\n",
			"import frappe\n@frappe.whitelist()\ndef f():\n\tfrappe.has_permission('Item', 'read', throw=True)\n",
			"import frappe\nclass A:\n\t@frappe.whitelist(methods=['POST'])\n\tdef f(self):\n\t\t'''doc'''\n\t\tself.check_permission('write')\n\t\treturn 1\n",
			"import frappe\n@frappe.whitelist()\ndef f(name):\n\tfrappe.get_doc('Item', name).check_permission('read')\n",
			"import frappe\n@frappe.whitelist()\ndef f():\n\tfrappe.permissions.check_doctype_permission('Item')\n",
		)
		for source in checked:
			self.assertEqual(scan_source(source, "ai_munimji/api.py").problems, [], source)
