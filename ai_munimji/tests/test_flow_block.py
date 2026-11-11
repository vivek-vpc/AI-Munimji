"""The Flow block on a request: reorder request -> purchase request -> Draft Purchase Order (Group 2, F3 of the production-readiness review).

Each step is a link to its record, the step the request on the screen belongs to is marked, a reorder that was approved and has no purchase request yet says so (and asks to be shown again),
a request that was changed shows what replaced it, and an item with no vendor history says in plain words that no comparison was possible and what to do. Everything that is text of ERPNext's
(the item, the vendor, the order's number) is escaped. It is read as the signed-in person.
"""

import re

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji import api, flow, markup
from ai_munimji.stores import frappe_core_stores
from ai_munimji.tests.helpers import make_user
from ai_munimji.tests.test_vendor_comparison import FakeBuyer, FlowCase

PO = "PUR-ORD-FAKE-0001"


def steps_of(html: str) -> list[str]:
	"""The text of each of the three steps, in order (tags and the arrows between them removed)."""
	cells = re.split(r'<div role="listitem"', html)[1:]
	plain = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)) for c in cells]
	return [
		re.sub(r" ([.,;:])", lambda m: m.group(1), c) for c in plain
	]  # a link in the middle of a sentence leaves a space before the full stop


def marked(html: str) -> int:
	"""The number (1 to 3) of the step that is marked as the one the request belongs to."""
	cells = re.split(r'<div role="listitem"', html)[1:]
	here = [i + 1 for i, c in enumerate(cells) if c.startswith(' aria-current="step"')]
	assert len(here) == 1, f"one step is marked, not {here}"
	return here[0]


class TheFlowOfAReorder(FlowCase):
	def reorder(self) -> str:
		return self.raise_a_reorder()

	def purchase_request(self, reorder: str) -> str:
		self.answer(reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(purchase,) = self.pending("procurement.po")
		return purchase["id"]

	def shown(self, request: str, user: str | None = None) -> dict:
		frappe.set_user(user or self.approver)
		try:
			return api.flow(request)
		finally:
			frappe.set_user("Administrator")

	def test_a_reorder_waiting_for_an_answer_is_step_one_and_the_others_wait_for_it(self):
		shown = self.shown(self.reorder())
		one, two, three = steps_of(shown["html"])
		self.assertEqual(marked(shown["html"]), 1)
		self.assertIn("Reorder request", one)
		self.assertIn("Waiting for an answer", one)
		self.assertIn("Made after the reorder is approved.", two)
		self.assertIn("Not yet", three)
		self.assertEqual(shown["refresh_in"], 0, "nothing is coming: the form need not ask again")

	def test_an_approved_reorder_with_no_purchase_request_yet_says_it_is_being_made_and_asks_again(self):
		reorder = self.reorder()
		self.answer(reorder, "approve")
		shown = self.shown(reorder)
		one, two, _ = steps_of(shown["html"])
		self.assertIn("Approved by flow.approver@example.com", one)
		self.assertIn("Being made", two)
		self.assertIn("The purchase request appears here in about a minute.", two)
		self.assertIn("If it does not, the next scheduled check", two)
		self.assertEqual(shown["refresh_in"], flow.POLL_SECONDS)

	def test_once_the_job_has_run_the_second_step_links_to_the_purchase_request(self):
		reorder = self.reorder()
		purchase = self.purchase_request(reorder)
		shown = self.shown(reorder)
		_, two, three = steps_of(shown["html"])
		self.assertIn(f'href="/app/munimji-approval-request/{purchase}"', shown["html"])
		self.assertIn("Waiting for an answer", two)
		self.assertIn("Recommended: A fake supplier", two)
		self.assertIn("Not yet", three)
		self.assertEqual(shown["refresh_in"], 0)
		self.assertEqual(marked(shown["html"]), 1, "the screen is the reorder request")

	def test_the_purchase_request_is_step_two_and_links_back_to_the_reorder(self):
		reorder = self.reorder()
		purchase = self.purchase_request(reorder)
		shown = self.shown(purchase)
		self.assertEqual(marked(shown["html"]), 2)
		self.assertIn(f'href="/app/munimji-approval-request/{reorder}"', shown["html"])

	def test_the_draft_order_is_a_link_and_is_still_there_after_the_request_is_reloaded(self):
		reorder = self.reorder()
		purchase = self.purchase_request(reorder)
		self.answer(purchase, "approve")
		for request, step in ((purchase, 2), (reorder, 1)):
			shown = self.shown(request)  # a reload is another call: nothing is kept in the browser
			self.assertEqual(marked(shown["html"]), step)
			self.assertIn(f'<a href="/app/purchase-order/{PO}">{PO}</a>', shown["html"])
			self.assertIn("Made as a draft", steps_of(shown["html"])[2])
			self.assertIn("Review and submit it in ERPNext.", steps_of(shown["html"])[2])
		self.assertIn("Approved by flow.approver@example.com", steps_of(self.shown(purchase)["html"])[1])

	def test_a_dismissed_purchase_request_says_nothing_was_ordered(self):
		purchase = self.purchase_request(self.reorder())
		self.answer(purchase, "dismiss")
		_, two, three = steps_of(self.shown(purchase)["html"])
		self.assertIn("Dismissed", two)
		self.assertIn("Nothing was ordered.", three)

	def test_a_dismissed_reorder_says_the_vendors_were_not_compared(self):
		reorder = self.reorder()
		self.answer(reorder, "dismiss")
		one, two, _ = steps_of(self.shown(reorder)["html"])
		self.assertIn("Dismissed", one)
		self.assertIn("the vendors were not compared", two)

	def test_a_changed_request_shows_what_replaced_it_and_the_new_one_shows_what_it_replaced(self):
		purchase = self.purchase_request(self.reorder())
		changed = self.answer(purchase, "change_qty", qty=77)
		self.assertEqual(changed["status"], "revised", changed)
		replacement = changed["approval"]
		self.assertNotEqual(replacement, purchase)
		old = self.shown(purchase)["html"]
		self.assertIn("Changed", steps_of(old)[1])
		self.assertIn("This request was changed. It was replaced by the new request.", steps_of(old)[1])
		self.assertIn(f'href="/app/munimji-approval-request/{replacement}"', old)
		new = self.shown(replacement)["html"]
		self.assertIn(f'href="/app/munimji-approval-request/{purchase}"', new)
		self.assertIn("Earlier version", steps_of(new)[1])
		reorder_view = self.shown(frappe_core_stores(system=True).approvals.list("decided", 10)[0]["id"])[
			"html"
		]
		self.assertIn(
			f'href="/app/munimji-approval-request/{replacement}"',
			reorder_view,
			"the reorder leads to the request that stands",
		)

	def test_a_request_that_is_not_part_of_the_flow_has_no_block(self):
		frappe_core_stores(system=True).approvals.insert(
			"notice-1",
			"inventory.alert",
			'{"title": "Low"}',
			"stock_notice",
			"n1",
			"2026-10-16T08:00:00+00:00",
			None,
		)
		self.assertEqual(self.shown("notice-1"), {"html": "", "refresh_in": 0})

	def test_anyone_who_may_read_requests_may_see_the_flow_and_nobody_else(self):
		reorder = self.reorder()
		self.assertIn("Reorder request", self.shown(reorder, self.viewer)["html"])
		self.assertIn("Reorder request", self.shown(reorder, self.manager)["html"])
		stranger = make_user("flow.stranger@example.com", ())
		with self.assertRaises(frappe.PermissionError):
			self.shown(reorder, stranger)


class TheTextOfErpnextIsNeverMarkup(FlowCase):
	ITEM = '<img src=x onerror="alert(1)">'
	VENDOR = "<script>alert('vendor')</script> Ltd"

	def make_erp(self) -> FakeBuyer:
		return FakeBuyer(item_name=self.ITEM, supplier_name=self.VENDOR)

	def test_the_flow_block_escapes_what_an_item_and_a_vendor_are_called(self):
		reorder = self.raise_a_reorder()
		self.answer(reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(purchase,) = self.pending("procurement.po")
		self.answer(purchase["id"], "approve")
		for request in (reorder, purchase["id"]):
			frappe.set_user(self.viewer)
			try:
				html = api.flow(request)["html"]
			finally:
				frappe.set_user("Administrator")
			self.assertNotIn("<script", html)
			self.assertNotIn("<img", html)
			self.assertNotIn(
				'onerror="', html, "an attribute of ours is quoted, and what was typed cannot break out of it"
			)
			self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", html)

	def test_the_sentence_after_an_answer_escapes_it_too(self):
		reorder = self.raise_a_reorder()
		self.answer(reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(purchase,) = self.pending("procurement.po")
		said = self.answer(purchase["id"], "approve")
		self.assertNotIn("<script", said["message_html"])
		self.assertNotIn("<img", said["message_html"])


class TestTheMarkupHelpers(IntegrationTestCase):
	def test_text_is_escaped_in_text_and_in_a_quoted_attribute(self):
		self.assertEqual(
			markup.esc("<b>\"x\" & 'y'</b>"), "&lt;b&gt;&quot;x&quot; &amp; &#x27;y&#x27;&lt;/b&gt;"
		)
		self.assertEqual(markup.esc(None), "")
		self.assertEqual(markup.esc(7), "7")

	def test_a_link_is_built_from_a_path_and_a_label_that_are_both_escaped(self):
		self.assertEqual(
			markup.link(markup.form_path("Purchase Order", 'PO"><script>'), "<x>"),
			'<a href="/app/purchase-order/PO%22%3E%3Cscript%3E">&lt;x&gt;</a>',
		)

	def test_the_paths_are_the_desks(self):
		self.assertEqual(
			markup.form_path("Munimji Approval Request", "abc"), "/app/munimji-approval-request/abc"
		)
		self.assertEqual(
			markup.form_path("Material Request", "MAT-MR-0001"), "/app/material-request/MAT-MR-0001"
		)
		self.assertEqual(markup.list_path("Munimji Approval Request"), "/app/munimji-approval-request")


class TheFlowOfAnItemWithNoVendorHistory(FlowCase):
	def make_erp(self) -> FakeBuyer:
		return FakeBuyer(offers=False)

	def test_it_says_in_plain_words_that_no_comparison_was_possible_and_what_to_do(self):
		reorder = self.raise_a_reorder()
		self.answer(reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(manual,) = self.pending("procurement.manual")
		frappe.set_user(self.approver)
		try:
			from_reorder = api.flow(reorder)["html"]
			from_manual = api.flow(manual["id"])
			text = steps_of(from_manual["html"])
		finally:
			frappe.set_user("Administrator")
		self.assertIn(f'href="/app/munimji-approval-request/{manual["id"]}"', from_reorder)
		self.assertIn(
			"No vendor could be compared for this item, so no purchase request was made.",
			steps_of(from_reorder)[1],
		)
		self.assertEqual(marked(from_manual["html"]), 2)
		self.assertIn(
			"No supplier is listed for this item and the ERP has no past purchase orders for it", text[1]
		)
		self.assertIn(
			"What to do: order it in ERPNext by hand, then press “Got it” on that request.", text[1]
		)
		self.assertIn("It is ordered in ERPNext by hand.", text[2])
		self.assertEqual(from_manual["refresh_in"], 0)

	def test_once_got_it_is_pressed_the_instruction_goes(self):
		reorder = self.raise_a_reorder()
		self.answer(reorder, "approve")
		(work_order,) = self.waiting_work_orders()
		self.the_job(work_order["id"])
		(manual,) = self.pending("procurement.manual")
		self.answer(manual["id"], "ack")
		frappe.set_user(self.approver)
		try:
			text = steps_of(api.flow(manual["id"])["html"])
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("What to do", text[1])
		self.assertIn("Answered by flow.approver@example.com", text[1])
