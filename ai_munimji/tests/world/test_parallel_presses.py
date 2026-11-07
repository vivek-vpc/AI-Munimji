"""Two presses of one button, on two real database connections at the same moment, make one order.

The file lock the client used first only holds on one server. Two workers, or two servers on one database, are two transactions that do not see each other: both look for an order, both
find none, both make one. These tests are the proof that they do not: every press here is its own thread with its own connection, started together, and the lookup is slowed down so that
the second press certainly arrives while the first is between "no order yet" and "order made".
"""

import time
from unittest import mock

import frappe
from ai_munimji_engine.packs.stock_procurement.erp import PurchaseOrderDraft

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.world.parallel import ParallelCase, on_own_connections

REF = "custom_agent_ref"


def slowed(original):
	"""A lookup that takes a second after it has answered: the window in which a second press can slip in."""

	def slow(self, *args):
		found = original(self, *args)
		time.sleep(1.0)
		return found

	return slow


WINDOW = (FrappeERPClient, "_already_made")


def plain_look(self, doctype, reference):
	"""The look the client first had: a search by reference in the press's own view of the database."""
	found = self.find_by_reference(doctype, reference)
	return found.name if found else None


class TestParallelPresses(ParallelCase):
	def draft(self, reference: str, qty: float = 3.0) -> PurchaseOrderDraft:
		return PurchaseOrderDraft(
			supplier=self.names["s1"],
			item_code=self.names["writes"],
			qty=qty,
			rate=12.0,
			uom="Nos",
			required_by=self.required_by(),
			reference=reference,
			approved_by="approver via desk",
		)

	def press(self, reference: str):
		return lambda: FrappeERPClient().create_purchase_order(self.draft(reference))

	def orders(self, reference: str) -> list[dict]:
		rows = self.committed_documents("Purchase Order", {REF: reference, "docstatus": ["<", 2]})
		for row in rows:
			self.remember("Purchase Order", row["name"])
		return rows

	def test_two_presses_on_two_connections_make_one_order(self):
		ref = f"WT-par2-{frappe.generate_hash(length=6)}"
		with mock.patch.object(*WINDOW, slowed(FrappeERPClient._already_made)):
			results = on_own_connections(self.person("approver"), [self.press(ref), self.press(ref)])
		failures = [r for r in results if isinstance(r, BaseException)]
		self.assertFalse(failures, failures)
		self.assertTrue(all(r.ok for r in results), results)
		self.assertEqual(
			len({r.name for r in results}), 1, f"both presses were told the same order: {results}"
		)
		self.assertEqual(len(self.orders(ref)), 1, "exactly one order exists for the reference")

	def test_five_presses_make_one_order(self):
		ref = f"WT-par5-{frappe.generate_hash(length=6)}"
		with mock.patch.object(*WINDOW, slowed(FrappeERPClient._already_made)):
			results = on_own_connections(self.person("approver"), [self.press(ref) for _ in range(5)])
		failures = [r for r in results if isinstance(r, BaseException)]
		self.assertFalse(failures, failures)
		self.assertEqual(len({r.name for r in results}), 1, results)
		self.assertEqual(len(self.orders(ref)), 1)

	def test_presses_for_different_references_make_one_order_each(self):
		refs = [f"WT-par-{i}-{frappe.generate_hash(length=6)}" for i in range(2)]
		started = time.time()
		results = on_own_connections(self.person("approver"), [self.press(r) for r in refs])
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual([len(self.orders(r)) for r in refs], [1, 1], "two references, two orders")
		self.assertLess(time.time() - started, 60, "and neither waited long for the other")

	def test_the_negative_control_a_plain_look_without_the_lock_makes_two_orders(self):
		# the first design: look in this transaction's own view for an order of the reference, then make one. The file lock it had was released before the first press committed.
		ref = f"WT-parno-{frappe.generate_hash(length=6)}"
		with (
			mock.patch.object(*WINDOW, slowed(plain_look)),
			mock.patch.object(FrappeERPClient, "_hold", return_value=None),
		):
			results = on_own_connections(self.person("approver"), [self.press(ref), self.press(ref)])
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual(
			len(self.orders(ref)),
			2,
			"without the lock and the locking read the guard misses the first press's uncommitted order: the test can fail",
		)

	def test_the_negative_control_the_lock_without_the_locking_read_still_makes_two_orders(self):
		# the lock makes the second press wait for the first to commit; but a plain read in the second press's own view (REPEATABLE READ) still does not see what was committed after
		# that view began. This is why the look under the lock is a locking read.
		ref = f"WT-parlk-{frappe.generate_hash(length=6)}"
		with mock.patch.object(*WINDOW, slowed(plain_look)):
			results = on_own_connections(self.person("approver"), [self.press(ref), self.press(ref)])
		self.assertFalse([r for r in results if isinstance(r, BaseException)], results)
		self.assertEqual(len(self.orders(ref)), 2, "the lock alone is not enough: the test can fail")
