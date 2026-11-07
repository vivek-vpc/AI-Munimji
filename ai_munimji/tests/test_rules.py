"""Rules about reading and acting, enforced on the source of the app (no site needed, it runs in a second):

1. `frappe.get_all` ignores permissions. It is allowed in the scheduled job module only, which runs as the system on purpose. Everywhere else a read goes through `frappe.get_list`, or
   through a document whose permission was checked.
2. Every method that a browser or an API client can call (`@frappe.whitelist`) checks the caller's permission as its FIRST statement, and none is open to guests.
3. `ignore_permissions=True` (and `flags.ignore_permissions = True`, and `frappe.set_user`) is allowed in the install and uninstall hooks only, which create and remove the app's own roles
   and records from the command line. Nowhere else: not in the ERP client, not in a button, not in a job.
4. The ERP client's system mode, `FrappeERPClient(system=True)`, and the stores' system mode, `frappe_core_stores(system=True)`, are built in the scheduled job module only
   (`jobs.system_erp()`, `jobs.system_stores()`).
5. The ERP client reads through `frappe.get_list` and the document APIs only: no `frappe.db` call at all, no `get_all`, no cached read (those do not apply the person's permissions).
6. The same holds for the stores (ai_munimji/stores): they read with `frappe.get_list` and documents and write through documents. Two modules are named exceptions, with the reason:
   `unit.py` (the savepoint: transaction control, no read) and `locks.py` (row locks: a locking read that returns a name, which the caller then reads through the permission rules).

If this fails, the code does not satisfy the rules the app is built to; fix the code, not the test. An exception is a decision: add the module to the list that names it, with the reason.
"""

import ast
import unittest

from ai_munimji.tests import scan

# Modules that run as the system, started by the scheduler and by nobody's request. Phase 5 replaces jobs.py; its successor is listed here when it exists.
SCHEDULED_JOB_MODULES = {"ai_munimji/jobs.py"}
# Modules that run once, from the command line, when the app is installed or removed.
LIFECYCLE_MODULES = {"ai_munimji/install.py", "ai_munimji/uninstall.py"}
ERP_CLIENT_MODULE = "ai_munimji/erp_client.py"
STORE_PREFIX = "ai_munimji/stores/"
STORE_EXCEPTIONS = {
	"ai_munimji/stores/unit.py",
	"ai_munimji/stores/locks.py",
}  # transaction control; row locks
SYSTEM_BUILDERS = {"FrappeERPClient", "frappe_core_stores"}  # what has a system mode
NOT_PERMISSION_AWARE = {
	"get_all",
	"get_cached_doc",
	"get_cached_value",
	"get_single",
	"get_single_value",
	"get_value",
}  # frappe.<name>(...) reads that do not apply the person's rights


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


def _not_false(node: ast.AST) -> bool:
	"""Anything but a literal False: True, a variable, an expression (a value passed through from a caller is not known to be False)."""
	return not (isinstance(node, ast.Constant) and node.value is False)


def _is_frappe_db(node: ast.AST) -> bool:
	return isinstance(node, ast.Attribute) and node.attr == "db" and _frappe(node.value)


def _frappe_call_name(call: ast.Call) -> str | None:
	"""`name` of frappe.<name>(...), else None."""
	f = call.func
	return f.attr if isinstance(f, ast.Attribute) and _frappe(f.value) else None


def _is_system_client(call: ast.Call) -> bool:
	f = call.func
	name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
	return name in SYSTEM_BUILDERS and any(k.arg == "system" and _not_false(k.value) for k in call.keywords)


class Found:
	def __init__(self):
		self.problems: list[str] = []
		self.whitelisted: list[str] = []
		self.get_all_calls = 0
		self.ignore_permissions = 0
		self.system_clients = 0


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
		if isinstance(node, ast.Call):
			bypass = (
				any(k.arg == "ignore_permissions" and _not_false(k.value) for k in node.keywords)
				or _frappe_call_name(node) == "set_user"
			)
			if bypass:
				found.ignore_permissions += 1
				if filename not in LIFECYCLE_MODULES:
					found.problems.append(
						f"{filename}:{node.lineno}: ignore_permissions / set_user is allowed only in {sorted(LIFECYCLE_MODULES)}"
					)
			if _is_system_client(node):
				found.system_clients += 1
				if filename not in SCHEDULED_JOB_MODULES:
					found.problems.append(
						f"{filename}:{node.lineno}: a system mode (the ERP client's, the stores') is built only in {sorted(SCHEDULED_JOB_MODULES)} (jobs.system_erp(), jobs.system_stores())"
					)
			if filename == ERP_CLIENT_MODULE or (
				filename.startswith(STORE_PREFIX) and filename not in STORE_EXCEPTIONS
			):
				name = _frappe_call_name(node)
				if (
					(name in NOT_PERMISSION_AWARE)
					or _is_frappe_db(getattr(node.func, "value", None))
					or _is_get_all(node)
				):
					found.problems.append(
						f"{filename}:{node.lineno}: the ERP client and the stores read with frappe.get_list and documents only; this call does not apply the person's permissions"
					)
		if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
			targets = node.targets if isinstance(node, ast.Assign) else [node.target]
			if (
				node.value is not None
				and _not_false(node.value)
				and any(isinstance(t, ast.Attribute) and t.attr == "ignore_permissions" for t in targets)
			):
				found.ignore_permissions += 1
				if filename not in LIFECYCLE_MODULES:
					found.problems.append(
						f"{filename}:{node.lineno}: flags.ignore_permissions is allowed only in {sorted(LIFECYCLE_MODULES)}"
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
	def test_the_app_follows_the_rules(self):
		problems, whitelisted, scanned = [], [], []
		get_all_in_jobs = system_clients_in_jobs = bypasses_in_hooks = 0
		get_all_anywhere = 0
		for path in scan.python_files():
			name = scan.relative(path)
			scanned.append(name)
			found = scan_source(path.read_text(encoding="utf-8"), name)
			problems += found.problems
			whitelisted += found.whitelisted
			get_all_anywhere += found.get_all_calls
			if name in SCHEDULED_JOB_MODULES:
				get_all_in_jobs += found.get_all_calls
				system_clients_in_jobs += found.system_clients
			if name in LIFECYCLE_MODULES:
				bypasses_in_hooks += found.ignore_permissions
		self.assertEqual(problems, [])
		# positive controls: the scan sees what it is meant to see, so that it cannot pass by looking at nothing
		self.assertIn("answer", whitelisted)
		self.assertEqual(
			get_all_anywhere,
			0,
			"nothing in the app reads with get_all: the scheduled job reads through the stores and the system-mode client",
		)
		self.assertEqual(
			system_clients_in_jobs,
			2,
			"the scheduled job module builds the system-mode client and the system-mode stores, one place each, and the scan sees both",
		)
		self.assertGreaterEqual(
			bypasses_in_hooks,
			3,
			"the install and uninstall hooks create and remove roles and records with ignore_permissions, and the scan sees it",
		)
		self.assertIn(ERP_CLIENT_MODULE, scanned)
		self.assertIn("ai_munimji/stores/table.py", scanned)
		for module in SCHEDULED_JOB_MODULES | LIFECYCLE_MODULES | STORE_EXCEPTIONS | {ERP_CLIENT_MODULE}:
			self.assertTrue(
				(scan.ROOT / module).exists(), f"{module} is named in the rules but does not exist"
			)

	def test_the_scan_notices_a_permission_bypass_outside_the_install_hooks(self):
		bypasses = (
			"import frappe\nfrappe.get_doc({}).insert(ignore_permissions=True)\n",
			"import frappe\nfrappe.delete_doc('X', 'y', ignore_permissions=True)\n",
			"import frappe\nfrappe.get_list('Item', ignore_permissions=allowed)\n",  # passed through from a caller: not known to be False
			"import frappe\ndoc.flags.ignore_permissions = True\n",
			"import frappe\nfrappe.flags.ignore_permissions = True\n",
			"import frappe\nfrappe.set_user('Administrator')\n",
		)
		for source in bypasses:
			for module in ("ai_munimji/api.py", "ai_munimji/jobs.py", "ai_munimji/erp_client.py"):
				self.assertTrue(scan_source(source, module).problems, f"{module}: {source}")
			self.assertEqual(
				scan_source(source, "ai_munimji/install.py").problems, [], "the install hook may"
			)
		for source in (
			"import frappe\nfrappe.get_doc({}).insert(ignore_permissions=False)\n",
			"import frappe\nfrappe.get_doc({}).insert()\n",
		):
			self.assertEqual(scan_source(source, "ai_munimji/api.py").problems, [], source)

	def test_the_scan_notices_the_system_client_built_anywhere_but_the_job_module(self):
		system = (
			"from ai_munimji.erp_client import FrappeERPClient\nc = FrappeERPClient(system=True)\n",
			"from ai_munimji import erp_client\nc = erp_client.FrappeERPClient(system=True)\n",
			"from ai_munimji.erp_client import FrappeERPClient\nc = FrappeERPClient(system=mode)\n",
		)
		for source in system:
			for module in ("ai_munimji/api.py", "ai_munimji/erp_client.py", "ai_munimji/install.py"):
				self.assertEqual(len(scan_source(source, module).problems), 1, f"{module}: {source}")
			self.assertEqual(scan_source(source, "ai_munimji/jobs.py").problems, [])
		for source in (
			"c = FrappeERPClient()\n",
			"c = FrappeERPClient(system=False)\n",
			"c = FrappeERPClient(company='X')\n",
		):
			self.assertEqual(scan_source(source, "ai_munimji/api.py").problems, [], source)

	def test_the_scan_notices_a_read_in_the_erp_client_that_ignores_the_persons_rights(self):
		for source in (
			"import frappe\nx = frappe.db.get_value('Item', 'a', 'b')\n",
			"import frappe\nx = frappe.db.sql('select 1')\n",
			"import frappe\nx = frappe.db.exists('Item', 'a')\n",
			"import frappe\nx = frappe.db.count('Item')\n",
			"import frappe\nx = frappe.get_all('Item')\n",
			"import frappe\nx = frappe.get_cached_doc('Item', 'a')\n",
			"import frappe\nx = frappe.get_cached_value('Item', 'a', 'b')\n",
			"import frappe\nx = frappe.get_value('Item', 'a', 'b')\n",
		):
			self.assertTrue(scan_source(source, ERP_CLIENT_MODULE).problems, source)
			if "get_all" not in source:
				self.assertEqual(
					scan_source(source, "ai_munimji/jobs.py").problems,
					[],
					"the job may read the database directly: only the ERP client is held to get_list",
				)
		for source in (
			"import frappe\nx = frappe.get_list('Item', fields=['name'])\n",
			"import frappe\nx = frappe.get_doc('Item', 'a')\n",
			"import frappe\nfrappe.has_permission('Item', 'read', throw=True)\n",
			"import frappe\nx = frappe.local.site\n",
		):
			self.assertEqual(scan_source(source, ERP_CLIENT_MODULE).problems, [], source)

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

	def test_the_scan_notices_the_system_stores_built_anywhere_but_the_job_module(self):
		source = "from ai_munimji.stores import frappe_core_stores\ncore = frappe_core_stores(system=True)\n"
		for module in (
			"ai_munimji/api.py",
			"ai_munimji/wiring.py",
			"ai_munimji/erp_client.py",
			"ai_munimji/stores/core.py",
		):
			self.assertEqual(len(scan_source(source, module).problems), 1, module)
		self.assertEqual(scan_source(source, "ai_munimji/jobs.py").problems, [])
		self.assertEqual(scan_source("core = frappe_core_stores()\n", "ai_munimji/wiring.py").problems, [])
		self.assertEqual(
			scan_source("core = frappe_core_stores(system=False)\n", "ai_munimji/wiring.py").problems, []
		)

	def test_the_scan_notices_a_read_in_a_store_that_ignores_the_persons_rights(self):
		for source in (
			"import frappe\nx = frappe.db.get_value('Item', 'a', 'b')\n",
			"import frappe\nx = frappe.db.sql('select 1')\n",
			"import frappe\nfrappe.db.delete('Munimji Lock')\n",
			"import frappe\nx = frappe.get_all('Item')\n",
			"import frappe\nx = frappe.get_cached_doc('Item', 'a')\n",
		):
			for module in (
				"ai_munimji/stores/table.py",
				"ai_munimji/stores/core.py",
				"ai_munimji/stores/stock.py",
			):
				self.assertTrue(scan_source(source, module).problems, f"{module}: {source}")
			for exception in STORE_EXCEPTIONS:
				if "get_all" not in source:
					self.assertEqual(
						scan_source(source, exception).problems,
						[],
						f"{exception} is a named exception: {source}",
					)
		for source in (
			"import frappe\nx = frappe.get_list('Item', fields=['name'])\n",
			"import frappe\nx = frappe.get_doc('Item', 'a', for_update=True)\n",
			"import frappe\ndoc.save()\n",
		):
			self.assertEqual(scan_source(source, "ai_munimji/stores/table.py").problems, [], source)
