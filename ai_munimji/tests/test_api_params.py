"""The parameters of an answer are read safely: anything that is not a JSON object is refused with one plain sentence, never a traceback or a server error.

The calls go through Frappe's own request handler (`frappe.handler.execute_cmd`), the way a browser's `frappe.call` reaches the method: whitelist, HTTP method and argument types included.
"""

import json
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe import handler
from frappe.tests import IntegrationTestCase

from ai_munimji import api
from ai_munimji.tests.helpers import make_request, make_user


class TestTheParametersOfAnAnswer(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"params_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		self.request = make_request("Order bolts")
		frappe.set_user(make_user("params.approver@example.com", ("Munimji Approver",)))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)

	def post(self, **form):
		"""The call as the browser's frappe.call makes it: POST, through the handler."""
		with (
			mock.patch.object(frappe.local, "form_dict", frappe._dict(form), create=True),
			mock.patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True),
		):
			return handler.execute_cmd("ai_munimji.api.answer")

	def answer(self, params):
		return self.post(approval_id=self.request.name, action="dismiss", params=params)

	def assertRefused(self, out):
		self.assertEqual((out["ok"], out["status"]), (False, "refused"), out)
		message = out["message"]
		self.assertTrue(message.endswith(".") and "\n" not in message, message)
		for word in ("Traceback", "Error", "JSON", "Exception", "line 1"):
			self.assertNotIn(word, message)

	def test_text_that_is_not_json_is_refused(self):
		self.assertRefused(self.answer("not json"))
		self.assertRefused(self.answer("{'qty': 5}"))  # Python's quotes, not JSON's
		self.assertRefused(self.answer('{"qty": '))

	def test_a_value_that_is_not_an_object_is_refused(self):
		for text in ("[1]", "5", "null", '"text"', "true", "[]"):
			with self.subTest(text):
				self.assertRefused(self.answer(text))

	def test_an_object_with_a_huge_string_is_refused_and_kept_out_of_the_records(self):
		self.assertRefused(self.answer(json.dumps({"qty": "9" * 100_000})))
		self.assertRefused(self.answer("[" * 100_000))  # nesting deep enough to exhaust the parser
		self.assertEqual(
			frappe.db.get_value("Munimji Approval Request", self.request.name, "status"), "pending"
		)

	def test_a_refused_answer_changes_nothing(self):
		self.assertRefused(self.answer("[1]"))
		row = frappe.get_doc("Munimji Approval Request", self.request.name)
		self.assertEqual((row.status, row.answer), ("pending", None))

	def test_nothing_sent_and_an_empty_object_and_a_valid_object_reach_the_engine(self):
		# a request that does not exist: the parameters are read, and the engine is the one that says there is nothing to answer
		for params in (None, "", "{}", json.dumps({"qty": 5}), json.dumps({"supplier": "SUP-1"})):
			with self.subTest(params):
				out = self.post(approval_id="no-such-request", action="change_qty", params=params)
				self.assertNotEqual(out.get("status"), "refused", out)
				self.assertFalse(out["ok"])

	def test_the_reader_alone(self):
		self.assertIsNone(api.read_params(None))
		self.assertIsNone(api.read_params(""))
		self.assertEqual(api.read_params('{"qty": 150}'), {"qty": 150})
		for bad in ("x", "[1]", "5", "null", "9" * (api.MAX_PARAMS_CHARS + 1)):
			with self.assertRaises(ValueError):
				api.read_params(bad)
