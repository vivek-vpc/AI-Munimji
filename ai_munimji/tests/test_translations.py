"""Every word a person reads goes through _() in Python and __() in JavaScript, and the template of the translations (locale/main.pot) holds all of them.

In Frappe v16 the template is made by `bench generate-pot-file --app ai_munimji` (Babel reads the Python, the JavaScript and the DocType files); `bench update-po-files --app ai_munimji`
brings each language file (locale/<language>.po) up to date with it, and `bench compile-po-to-mo --app ai_munimji` makes the binaries Frappe reads (`bench build` and `bench update` do
that too). The extractor never complains about a string that is not wrapped: such a string is simply absent. So this file looks for them itself.
"""

import ast
import json
import re
import unittest

from babel.messages.pofile import read_po

from ai_munimji.tests import scan

POT = scan.PACKAGE / "locale" / "main.pot"

# Calls whose words reach a person, and the keywords of those calls that carry words.
USER_FACING = {"throw", "msgprint", "errprint"}
TEXT_KEYWORDS = {"msg", "message", "title"}
# `_()` with something that is not a literal cannot be extracted. These are the two places that translate the label of a field of a DocType, which is extracted from the DocType's JSON.
DYNAMIC_ALLOWED = {("ai_munimji/settings_map.py", "label_of"), ("ai_munimji/settings_map.py", "_event_label")}


def _is_translation(node: ast.AST) -> bool:
	return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"


def _has_letters(value: str) -> bool:
	return re.search(r"[A-Za-z]", value) is not None


def words_outside_translation(expression: ast.AST) -> list[ast.AST]:
	"""String literals and f-strings in an expression that are not inside a call of _()."""
	found: list[ast.AST] = []

	def walk(node: ast.AST) -> None:
		if _is_translation(node):
			return
		if isinstance(node, ast.JoinedStr):
			found.append(node)
			return
		if isinstance(node, ast.Constant) and isinstance(node.value, str) and _has_letters(node.value):
			found.append(node)
			return
		for child in ast.iter_child_nodes(node):
			walk(child)

	walk(expression)
	return found


class _Scan(ast.NodeVisitor):
	def __init__(self, filename: str):
		self.filename = filename
		self.problems: list[str] = []
		self.messages: list[str] = []  # the literals inside _()
		self.calls_seen = 0
		self.function_stack: list[str] = []

	def visit_FunctionDef(self, node):
		self.function_stack.append(node.name)
		self.generic_visit(node)
		self.function_stack.pop()

	visit_AsyncFunctionDef = visit_FunctionDef

	def _report(self, node: ast.AST, what: str) -> None:
		self.problems.append(f"{self.filename}:{node.lineno}: {what}")

	def _check_words(self, call: ast.Call, name: str) -> None:
		self.calls_seen += 1
		expressions = ([call.args[0]] if call.args else []) + [
			k.value for k in call.keywords if k.arg in TEXT_KEYWORDS
		]
		for expression in expressions:
			for literal in words_outside_translation(expression):
				self._report(literal, f"words for a person outside _() in {name}(...)")

	def visit_Call(self, node: ast.Call):
		function = node.func
		name = (
			function.attr
			if isinstance(function, ast.Attribute)
			else function.id
			if isinstance(function, ast.Name)
			else ""
		)
		from_frappe = isinstance(function, ast.Name) or (
			isinstance(function, ast.Attribute)
			and isinstance(function.value, ast.Name)
			and function.value.id == "frappe"
		)
		if name in USER_FACING and from_frappe:
			self._check_words(node, name)
		if _is_translation(node):
			argument = node.args[0] if node.args else None
			if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
				self.messages.append(argument.value)
			elif (
				self.filename,
				self.function_stack[-1] if self.function_stack else "",
			) not in DYNAMIC_ALLOWED:
				self._report(node, "_() with something that is not a string literal cannot be extracted")
		self.generic_visit(node)

	def visit_Raise(self, node: ast.Raise):
		call = node.exc
		if (
			isinstance(call, ast.Call)
			and isinstance(call.func, ast.Attribute)
			and isinstance(call.func.value, ast.Name)
			and call.func.value.id == "frappe"
		):
			if call.func.attr.endswith(("Error", "Exception")):
				self._check_words(call, f"raise frappe.{call.func.attr}")
		self.generic_visit(node)


def scan_python(source: str, filename: str) -> _Scan:
	scanner = _Scan(filename)
	scanner.visit(ast.parse(source, filename))
	return scanner


# JavaScript: a literal where words belong, found without a parser. The calls and keys below take words; a quote straight after the opening bracket or the colon is a bare literal.
JS_CALLS = r"(?:frappe\.(?:msgprint|throw|show_alert|confirm|prompt)|add_custom_button|set_intro|add_comment)"
JS_BARE = re.compile(
	rf"{JS_CALLS}\(\s*[\"'`]|\b(?:message|title|label|description|freeze_message|primary_action_label)\s*:\s*[\"'`]"
)
JS_TRANSLATED = re.compile(r"__\(\s*(?P<q>[\"'`])(?P<text>(?:\\.|(?!(?P=q)).)*)(?P=q)", re.S)


def _strip_js_comments(source: str) -> str:
	return re.sub(r"/\*.*?\*/|(?<!:)//[^\n]*", "", source, flags=re.S)


def scan_javascript(source: str, filename: str) -> tuple[list[str], list[str]]:
	"""(problems, the messages inside __())"""
	text = _strip_js_comments(source)
	# an empty literal ("" clears a note) holds no words
	problems = [
		f"{filename}:{text.count(chr(10), 0, m.start()) + 1}: words for a person outside __(): {m.group(0).strip()}"
		for m in JS_BARE.finditer(text)
		if text[m.end() : m.end() + 1] != text[m.end() - 1 : m.end()]
	]
	return problems, [m.group("text") for m in JS_TRANSLATED.finditer(text)]


class TestNoWordIsLeftUntranslated(unittest.TestCase):
	def test_python_every_message_to_a_person_is_translated(self):
		problems, seen, messages = [], 0, []
		for path in scan.python_files():
			scanner = scan_python(path.read_text(encoding="utf-8"), scan.relative(path))
			problems += scanner.problems
			seen += scanner.calls_seen
			messages += scanner.messages
		self.assertEqual(problems, [])
		self.assertGreaterEqual(
			seen, 3, "the scan found almost no throw/msgprint calls: it is looking in the wrong place"
		)
		self.assertGreaterEqual(
			len(messages), 8, "the scan found almost no _() calls: it is looking in the wrong place"
		)

	def test_javascript_every_text_to_a_person_is_translated(self):
		problems, translated = [], []
		for path in scan.javascript_files():
			found, messages = scan_javascript(path.read_text(encoding="utf-8"), scan.relative(path))
			problems += found
			translated += messages
		self.assertEqual(problems, [])
		self.assertGreaterEqual(
			len(translated), 3, "the scan found almost no __() calls: it is looking in the wrong place"
		)

	def test_the_scan_does_notice_a_bare_message(self):
		# negative controls: the same scanner, on code that breaks the rule
		bad = (
			'import frappe\nfrappe.throw("Not translated")\n',
			'import frappe\nfrappe.msgprint(f"Hello {name}")\n',
			'import frappe\nfrom frappe import _\nfrappe.throw(_("fine"), title="Bare title")\n',
			'import frappe\nfrom frappe import _\nfrappe.throw("a bare " + _("and a translated one"))\n',
			'import frappe\nraise frappe.ValidationError("Bare")\n',
			'import frappe\nfrom frappe import _\nfrappe.throw(_(f"Hello {name}"))\n',
			"from frappe import _\ndef f(text):\n\treturn _(text)\n",
			'from frappe import throw\nthrow("Bare")\n',
		)
		for source in bad:
			self.assertTrue(scan_python(source, "bad.py").problems, source)
		good = (
			'import frappe\nfrom frappe import _\nfrappe.throw(_("Fine {0}").format(x))\n',
			'import frappe\nfrom frappe import _\nfrappe.msgprint(found, title=_("Fine"), as_list=True, indicator="orange")\n',
			'import frappe\nfrom frappe import _\nraise frappe.ValidationError(_("Fine"))\n',
		)
		for source in good:
			self.assertEqual(scan_python(source, "good.py").problems, [], source)
		for source in (
			'frappe.msgprint("Bare");',
			"frappe.show_alert({message: 'Bare', indicator: 'green'});",
			'frm.add_custom_button("Bare", () => {});',
			"frappe.confirm(`Bare`)",
		):
			self.assertTrue(scan_javascript(source, "bad.js")[0], source)
		self.assertEqual(
			scan_javascript(
				'frappe.show_alert({message: __("Fine {0}", [x]), indicator: "green"}); // a "comment"',
				"good.js",
			)[0],
			[],
		)
		self.assertEqual(
			scan_javascript('frm.set_intro("");', "empty.js")[0], [], "an empty literal holds no words"
		)
		self.assertTrue(scan_javascript('frm.set_intro("x");', "one.js")[0], "one character is a word")


class TestTheTemplateHoldsEveryWord(unittest.TestCase):
	"""locale/main.pot is committed; dev/gate.sh makes it again with bench generate-pot-file and fails if it differs."""

	@classmethod
	def setUpClass(cls):
		if not POT.exists():
			raise unittest.SkipTest(
				"locale/main.pot has not been made yet: bench --site <site> generate-pot-file --app ai_munimji"
			)
		with POT.open("rb") as handle:
			cls.catalog = read_po(handle)
		cls.in_template = {m.id if isinstance(m.id, str) else m.id[0] for m in cls.catalog if m.id}

	def test_every_python_message_is_in_the_template(self):
		missing = []
		for path in scan.python_files():
			for message in scan_python(path.read_text(encoding="utf-8"), scan.relative(path)).messages:
				if message not in self.in_template:
					missing.append(f"{scan.relative(path)}: {message[:70]}")
		self.assertEqual(
			missing, [], "run bench generate-pot-file --app ai_munimji and commit locale/main.pot"
		)

	def test_every_javascript_message_is_in_the_template(self):
		missing = []
		for path in scan.javascript_files():
			for message in scan_javascript(path.read_text(encoding="utf-8"), scan.relative(path))[1]:
				if message not in self.in_template:
					missing.append(f"{scan.relative(path)}: {message[:70]}")
		self.assertEqual(missing, [])

	def test_every_label_and_description_of_every_doctype_is_in_the_template(self):
		missing = []
		for path in scan.doctype_files():
			data = json.loads(path.read_text(encoding="utf-8"))
			texts = [data["name"], data.get("description", "")]
			for field in data.get("fields", []):
				texts += [field.get("label", ""), field.get("description", "")]
			missing += [f"{path.stem}: {t[:60]}" for t in texts if t and t not in self.in_template]
		self.assertEqual(
			missing,
			[],
			"the extractor reads DocType files; a missing text here means the template is out of date",
		)
