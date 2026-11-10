"""A purchase return is not a delivery: it does not change a vendor's lead time or on-time rate.

A Purchase Receipt with is_return = 1 (goods sent back) carries the same purchase order as the receipt it returns and a negative quantity. The client answers from canned tables that apply
Frappe's filters, so what is checked is the question it asks (the filters), with every field of the answer pinned.
"""

import unittest
from datetime import date

from ai_munimji.erp_client import FrappeERPClient

TODAY = date(2026, 11, 9)
OPS = {
	"=": lambda a, b: a == b,
	"!=": lambda a, b: a != b,
	"in": lambda a, b: a in b,
	">=": lambda a, b: a is not None and a >= b,
	"<=": lambda a, b: a is not None and a <= b,
	">": lambda a, b: a is not None and a > b,
	"<": lambda a, b: a is not None and a < b,
}


class CannedClient(FrappeERPClient):
	"""The client of the app with its one low-level read answered from tables, by the filters it is given."""

	def __init__(self, tables: dict[str, list[dict]]) -> None:
		super().__init__()
		self.tables = tables
		self.asked: list[tuple[str, list]] = []

	def _list(self, doctype, fields, filters, order_by=None, parent=None, group_by=None):
		self.asked.append((doctype, filters))
		rows = [r for r in self.tables.get(doctype, []) if all(OPS[op](r.get(f), v) for f, op, v in filters)]
		return [{f: r.get(f) for f in fields} for r in rows]


def world(receipts: list[dict]) -> dict[str, list[dict]]:
	"""One order for BOLT (placed 1 Oct, promised 10 Oct) and the receipts given."""
	return {
		"Purchase Order Item": [
			{
				"parent": "PO-1",
				"item_code": "BOLT",
				"docstatus": 1,
				"qty": 100,
				"rate": 5,
				"base_rate": 5,
				"schedule_date": "2026-10-10",
			}
		],
		"Purchase Order": [
			{
				"name": "PO-1",
				"supplier": "S1",
				"supplier_name": "Supplier One",
				"transaction_date": "2026-10-01",
				"docstatus": 1,
				"currency": "INR",
				"conversion_rate": 1,
			}
		],
		"Supplier": [{"name": "S1", "supplier_name": "Supplier One", "disabled": 0, "country": "India"}],
		"Purchase Receipt Item": [
			{"parent": r["name"], "purchase_order": "PO-1", "item_code": "BOLT", "docstatus": 1}
			for r in receipts
		],
		"Purchase Receipt": receipts,
	}


DELIVERY_LATE = {
	"name": "PR-1",
	"posting_date": "2026-10-14",
	"docstatus": 1,
	"is_return": 0,
}  # 13 days after the order, 4 days after the promise
RETURN_EARLIER = {
	"name": "PR-RET",
	"posting_date": "2026-10-06",
	"docstatus": 1,
	"is_return": 1,
}  # booked with an earlier date: -ve quantity, the same order
RETURN_LATER = {"name": "PR-RET2", "posting_date": "2026-10-20", "docstatus": 1, "is_return": 1}


def offer(receipts):
	client = CannedClient(world(receipts))
	[found] = client.get_vendor_offers("BOLT", date(2026, 1, 1))
	return found, client


class TestAReturnIsNotADelivery(unittest.TestCase):
	def test_the_baseline_is_a_late_delivery(self):
		found, _ = offer([DELIVERY_LATE])
		self.assertEqual((found.lead_time_days, found.on_time_rate), (13.0, 0.0))

	def test_a_return_dated_before_the_delivery_does_not_make_the_vendor_faster_or_on_time(self):
		found, _ = offer([DELIVERY_LATE, RETURN_EARLIER])
		self.assertEqual((found.lead_time_days, found.on_time_rate), (13.0, 0.0))

	def test_a_return_dated_after_it_changes_nothing_either(self):
		found, _ = offer([DELIVERY_LATE, RETURN_LATER])
		self.assertEqual((found.lead_time_days, found.on_time_rate), (13.0, 0.0))

	def test_with_only_a_return_there_is_no_delivery_to_judge_by(self):
		found, _ = offer([RETURN_EARLIER])
		self.assertEqual((found.lead_time_days, found.on_time_rate), (None, None))

	def test_the_question_asked_leaves_returns_out_of_the_receipts_and_does_not_filter_the_orders(self):
		_, client = offer([DELIVERY_LATE, RETURN_EARLIER])
		receipts = [f for doctype, f in client.asked if doctype == "Purchase Receipt"]
		self.assertTrue(receipts and all(["is_return", "=", 0] in f for f in receipts), receipts)
		orders = [f for doctype, f in client.asked if doctype in ("Purchase Order", "Purchase Order Item")]
		self.assertTrue(orders and not any(row[0] == "is_return" for f in orders for row in f))
