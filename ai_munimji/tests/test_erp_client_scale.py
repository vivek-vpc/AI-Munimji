"""What the ERP client reads from the stock ledger no longer grows with the number of movements, and no longer lists every item to look at one (finding A2 of the
production-readiness review).

Before: `get_consumption` fetched one row per stock movement of the whole history window into Python, so its cost grew with transactions, not items; `list_items` read the first movement of
every item with a GROUP BY over the whole ledger, on every run and on every answer to a reorder request. Now the database adds up each item's movements of a day, the first movement of an
item is asked for once and kept, an item created longer ago than the window is not asked about at all, and one item is read without listing the rest.
"""

from datetime import date, timedelta
from unittest import mock

import frappe
from ai_munimji_engine.packs.stock_procurement.settings import Policy
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.tests.utils import ERPNextTestSuite
from frappe.utils import add_days, nowdate

from ai_munimji import erp_client
from ai_munimji.erp_client import FIRST_MOVEMENT_CACHE, HISTORY_LIMIT_DAYS, FrappeERPClient

WAREHOUSE = "_Test Warehouse - _TC"
LEDGER = "Stock Ledger Entry"


class Reads:
	"""Counts what `frappe.get_list` is asked for and how many rows it gives back, by DocType."""

	def __init__(self):
		self.calls: list[tuple[str, dict]] = []
		self.rows: dict[str, int] = {}
		self._real = frappe.get_list

	def __enter__(self):
		def counting(doctype, *args, **kwargs):
			got = self._real(doctype, *args, **kwargs)
			self.calls.append((doctype, kwargs))
			self.rows[doctype] = self.rows.get(doctype, 0) + len(got)
			return got

		self._patch = mock.patch.object(frappe, "get_list", counting)
		self._patch.start()
		return self

	def __exit__(self, *exc):
		self._patch.stop()

	def asked_about(self, doctype: str, code: str) -> int:
		return sum(1 for d, kw in self.calls if d == doctype and code in str(kw.get("filters")))


class TestTheLedgerReads(ERPNextTestSuite):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.cache.delete_value(FIRST_MOVEMENT_CACHE)
		self.item = make_item(
			f"_Munimji Scale Item {frappe.generate_hash(length=6)}", {"is_stock_item": 1}
		).name
		self.client = FrappeERPClient(system=True)
		self.client.voucher_types = [
			"Stock Entry"
		]  # what the issues below are: the rule is "the vouchers that count as use", and this is the only kind the test makes

	def issue(self, qty: float, days_ago: int):
		make_stock_entry(
			item_code=self.item, qty=qty, source=WAREHOUSE, posting_date=add_days(nowdate(), -days_ago)
		)

	def receive(self, qty: float, days_ago: int):
		make_stock_entry(
			item_code=self.item,
			qty=qty,
			to_warehouse=WAREHOUSE,
			rate=10,
			posting_date=add_days(nowdate(), -days_ago),
		)

	def test_the_database_adds_up_the_movements_of_a_day_and_the_rows_read_are_one_per_day(self):
		self.receive(100, 20)
		for qty in (1, 2, 3):  # three issues on one day
			self.issue(qty, 5)
		self.issue(4, 3)
		with Reads() as reads:
			usage = self.client.get_consumption([self.item], date.today() - timedelta(days=30), date.today())
		self.assertEqual(
			[(u.day, u.qty) for u in usage[self.item]],
			[(date.today() - timedelta(days=5), 6.0), (date.today() - timedelta(days=3), 4.0)],
		)
		self.assertEqual(reads.rows[LEDGER], 2, "two days of use are two rows, not the four movements")

	def test_what_is_read_does_not_grow_with_the_number_of_movements_on_a_day(self):
		self.receive(1000, 20)
		for _ in range(12):
			self.issue(1, 4)
		with Reads() as reads:
			usage = self.client.get_consumption([self.item], date.today() - timedelta(days=30), date.today())
		self.assertEqual([u.qty for u in usage[self.item]], [12.0])
		self.assertEqual(reads.rows[LEDGER], 1, "twelve movements of one day come back as one row")

	def test_the_sums_are_what_adding_the_movements_one_by_one_gives(self):
		self.receive(500, 40)
		for days_ago, qty in ((9, 2), (9, 1), (8, 3), (6, 1), (6, 1), (6, 7)):
			self.issue(qty, days_ago)
		rows = frappe.get_all(
			LEDGER,
			filters={"item_code": self.item, "actual_qty": ["<", 0], "is_cancelled": 0},
			fields=["posting_date", "actual_qty"],
		)
		by_hand: dict = {}
		for r in rows:
			by_hand[r.posting_date] = by_hand.get(r.posting_date, 0.0) - float(r.actual_qty)
		usage = self.client.get_consumption([self.item], date.today() - timedelta(days=30), date.today())
		self.assertEqual({u.day: u.qty for u in usage[self.item]}, by_hand)

	def test_the_first_movement_is_asked_for_once_and_then_kept(self):
		self.receive(10, 12)
		with Reads() as reads:
			first = self.client._first_movements([self.item])
		self.assertEqual(first[self.item], date.today() - timedelta(days=12))
		self.assertEqual(reads.asked_about(LEDGER, self.item), 1)
		with Reads() as reads:
			again = self.client._first_movements([self.item])
		self.assertEqual(again, first)
		self.assertEqual(
			reads.asked_about(LEDGER, self.item), 0, "the answer was kept: the ledger is not asked again"
		)

	def test_an_item_with_no_movement_yet_is_asked_about_again(self):
		with Reads() as reads:
			self.assertEqual(self.client._first_movements([self.item]), {})
			self.assertEqual(self.client._first_movements([self.item]), {})
		self.assertEqual(reads.asked_about(LEDGER, self.item), 2, "nothing known, nothing kept")

	def test_only_the_items_whose_first_movement_is_not_known_are_asked_for(self):
		other = make_item(f"_Munimji Scale Item {frappe.generate_hash(length=6)}", {"is_stock_item": 1}).name
		self.receive(10, 12)
		self.client._first_movements([self.item])
		make_stock_entry(item_code=other, qty=5, to_warehouse=WAREHOUSE, rate=10)
		with Reads() as reads:
			found = self.client._first_movements([self.item, other])
		self.assertEqual(set(found), {self.item, other})
		self.assertEqual((reads.asked_about(LEDGER, self.item), reads.asked_about(LEDGER, other)), (0, 1))

	def test_an_item_created_before_the_window_the_rules_read_is_not_asked_about(self):
		self.receive(10, 12)
		old = date.today() - timedelta(days=HISTORY_LIMIT_DAYS + 30)
		frappe.db.set_value("Item", self.item, "creation", f"{old} 10:00:00", update_modified=False)
		with Reads() as reads:
			infos = {i.code: i for i in self.client.get_items([self.item])}
		self.assertEqual(
			infos[self.item].created,
			old,
			"created long ago: that is when its history begins as far as the rules can tell",
		)
		self.assertEqual(reads.asked_about(LEDGER, self.item), 0)

	def test_a_recent_item_whose_first_movement_is_earlier_than_its_creation_starts_there(self):
		self.receive(10, 40)
		frappe.db.set_value(
			"Item", self.item, "creation", f"{add_days(nowdate(), -3)} 10:00:00", update_modified=False
		)
		(info,) = self.client.get_items([self.item])
		self.assertEqual(info.created, date.today() - timedelta(days=40))

	def test_one_item_is_read_without_listing_the_others(self):
		with Reads() as reads:
			(info,) = self.client.get_items([self.item])
		self.assertEqual(info.code, self.item)
		item_reads = [kw for d, kw in reads.calls if d == "Item"]
		self.assertEqual(len(item_reads), 1)
		self.assertIn(self.item, str(item_reads[0]["filters"]))
		self.assertEqual([i.code for i in self.client.get_items([])], [])
		self.assertIn(self.item, [i.code for i in self.client.list_items()], "the full list is still there")

	def test_a_person_who_may_not_read_the_ledger_is_told_the_start_of_the_history_is_unknown(self):
		real = frappe.has_permission
		with mock.patch.object(
			frappe,
			"has_permission",
			lambda doctype, *a, **kw: False if doctype == LEDGER else real(doctype, *a, **kw),
		):
			self.assertEqual(self.client._first_movements([self.item]), {})
		self.assertTrue(any("Stock Ledger Entry" in note for note in self.client.notes), self.client.notes)

	def test_the_window_that_exempts_old_items_is_the_longest_history_the_rules_can_ask_for(self):
		limit = next(m.le for m in Policy.model_fields["history_days"].metadata if hasattr(m, "le"))
		self.assertEqual(HISTORY_LIMIT_DAYS, limit)
		self.assertEqual(erp_client.LOOKUP_CHUNK, 200)
