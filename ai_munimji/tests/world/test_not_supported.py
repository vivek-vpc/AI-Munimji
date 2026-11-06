"""The part of the port that version 0.1 leaves out says so, in words, one method at a time (docs/KNOWN_LIMITATIONS.md lists them). It needs no data: it runs anywhere the app does."""

import ast
import inspect
import unittest
from datetime import date
from pathlib import Path

from ai_munimji import erp_client
from ai_munimji.erp_client import FrappeERPClient, NotSupportedInThisVersion

LIMITATIONS = Path(erp_client.__file__).resolve().parents[1] / "docs" / "KNOWN_LIMITATIONS.md"
TODAY = date(2026, 1, 1)
LEFT_OUT = {
	"get_receipt_lines": ((TODAY,), "goods receipts"),
	"get_stock_counts": ((TODAY,), "stock counts"),
	"get_stock_values": (([],), "value of stock"),
	"last_purchase_dates": (([],), "last bought"),
	"get_item_alternatives": (("X",), "item alternatives"),
	"get_supplier_contact": (("X",), "contact details"),
	"send_email": ((["a@example.com"], "subject", "body", "Purchase Order", "PO-1"), "e-mail"),
}


class TestWhatIsLeftOut(unittest.TestCase):
	def test_each_method_left_out_raises_a_clear_error_and_does_nothing_else(self):
		client = FrappeERPClient()
		for method, (args, words) in LEFT_OUT.items():
			with self.subTest(method):
				with self.assertRaises(NotSupportedInThisVersion) as caught:
					getattr(client, method)(*args)
				self.assertIn("is not supported in this version of AI Munimji", str(caught.exception))
				self.assertIn(words.lower(), str(caught.exception).lower())

	def test_a_document_type_the_stock_rules_do_not_read_is_refused_in_the_same_way(self):
		for doctype in ("Sales Invoice", "Journal Entry", "Customer"):
			with self.subTest(doctype), self.assertRaises(NotSupportedInThisVersion):
				FrappeERPClient().get_documents(doctype)

	def test_the_error_is_not_swallowed_into_an_empty_answer(self):
		# an engine caller that treats "unknown" as "none" must have to catch this on purpose: it is a NotImplementedError, never a return value
		self.assertTrue(issubclass(NotSupportedInThisVersion, NotImplementedError))

	def test_the_list_in_this_test_is_the_list_of_the_client_and_of_the_limitations_document(self):
		tree = ast.parse(inspect.getsource(FrappeERPClient))
		raising = set()
		for node in ast.walk(tree):
			if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
				if any(
					isinstance(n, ast.Raise)
					and isinstance(n.exc, ast.Call)
					and getattr(n.exc.func, "id", "") == "not_supported"
					for n in ast.walk(node)
				):
					raising.add(node.name)
		raising.discard(
			"get_documents"
		)  # refuses document types it does not read; it is listed in the document as such
		self.assertEqual(
			raising,
			set(LEFT_OUT),
			"a method that raises 'not supported' is missing here, or one listed here no longer does",
		)
		text = LIMITATIONS.read_text(encoding="utf-8")
		for method in LEFT_OUT:
			self.assertIn(f"`{method}`", text, f"docs/KNOWN_LIMITATIONS.md does not list {method}")
		self.assertIn("`get_documents`", text)
