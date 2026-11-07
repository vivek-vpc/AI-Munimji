"""What goes into the DocType stores comes back as it went in: moments in any time zone, empty values, very long text, JSON text, names, numbers that may be empty.

And the places where a DocType cannot be the same as SQLite are written down here as tests, so that a difference that grows, or one that goes away, fails something. Each is explained in
docs/STORES.md ("Where the DocType stores differ"). Nothing here is skipped: the shared store checks (test_stores_contract.py) already pass in full.
"""

from datetime import UTC, date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji.stores import convert, frappe_core_stores, frappe_stock_stores
from ai_munimji.stores.table import Exists
from ai_munimji.tests.helpers import empty_store_tables

ZONES = ("Asia/Kolkata", "UTC", "America/New_York", "Europe/Berlin", "Pacific/Auckland")
MOMENTS = (
	"2026-10-16T08:00:00+00:00",
	"2026-01-01T00:00:00+00:00",
	"2026-12-31T23:59:59+00:00",
	"2026-10-16T08:00:00.123456+00:00",
)


class TestMomentsThatCrossTheLine(IntegrationTestCase):
	def test_what_the_engine_writes_comes_back_unchanged_in_every_zone(self):
		for name in ZONES:
			zone = ZoneInfo(name)
			for text in MOMENTS:
				with self.subTest(zone=name, moment=text):
					self.assertEqual(convert.from_datetime(convert.to_datetime(text, zone), zone), text)

	def test_the_column_holds_the_wall_clock_of_the_site_not_of_utc(self):
		self.assertEqual(
			convert.to_datetime("2026-10-16T08:00:00+00:00", ZoneInfo("Asia/Kolkata")),
			datetime(2026, 10, 16, 13, 30),
		)
		self.assertEqual(
			convert.to_datetime("2026-10-16T08:00:00+00:00", ZoneInfo("America/New_York")),
			datetime(2026, 10, 16, 4, 0),
		)
		self.assertEqual(
			convert.to_datetime("2026-01-16T08:00:00+00:00", ZoneInfo("Europe/Berlin")),
			datetime(2026, 1, 16, 9, 0),
		)

	def test_another_offset_comes_back_as_the_same_moment_in_utc_and_no_offset_is_taken_as_utc(self):
		zone = ZoneInfo("Asia/Kolkata")
		self.assertEqual(
			convert.from_datetime(convert.to_datetime("2026-10-16T13:30:00+05:30", zone), zone),
			"2026-10-16T08:00:00+00:00",
		)
		self.assertEqual(
			convert.from_datetime(convert.to_datetime("2026-10-16T08:00:00", zone), zone),
			"2026-10-16T08:00:00+00:00",
		)
		self.assertEqual(
			convert.from_datetime(convert.to_datetime("2026-10-16T08:00:00Z", zone), zone),
			"2026-10-16T08:00:00+00:00",
		)

	def test_nothing_is_nothing(self):
		for empty in (None, ""):
			self.assertIsNone(convert.to_datetime(empty))
			self.assertIsNone(convert.from_datetime(empty))
			self.assertIsNone(convert.to_date(empty))
			self.assertIsNone(convert.from_date(empty))

	def test_the_hour_that_happens_twice_when_summer_time_ends_reads_back_as_its_first_pass(self):
		# Berlin, 25 October 2026: at 01:00 UTC the clocks go from 03:00 back to 02:00, so 02:30 is on the wall twice. A wall clock cannot say which; the first is chosen.
		zone = ZoneInfo("Europe/Berlin")
		first, second = "2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00"
		self.assertEqual(convert.to_datetime(first, zone), convert.to_datetime(second, zone))
		self.assertEqual(convert.from_datetime(convert.to_datetime(first, zone), zone), first)
		self.assertEqual(
			convert.from_datetime(convert.to_datetime(second, zone), zone),
			first,
			"the later pass reads back an hour early: the one limit of a wall clock",
		)

	def test_the_hour_that_does_not_exist_when_summer_time_begins_is_never_written(self):
		zone = ZoneInfo("Europe/Berlin")  # 29 March 2026: 02:00 jumps to 03:00 at 01:00 UTC
		for text in ("2026-03-29T00:59:59+00:00", "2026-03-29T01:00:00+00:00", "2026-03-29T01:30:00+00:00"):
			self.assertEqual(convert.from_datetime(convert.to_datetime(text, zone), zone), text)

	def test_dates_are_dates(self):
		self.assertEqual(convert.to_date("2026-10-16"), date(2026, 10, 16))
		self.assertEqual(convert.from_date(date(2026, 10, 16)), "2026-10-16")
		with self.assertRaises(ValueError):
			convert.to_date("16/10/2026")


class StoreCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"trip_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = frappe_core_stores(system=True)
		self.stock = frappe_stock_stores(self.core)

	def tearDown(self):
		frappe.db.rollback(save_point=self.savepoint)


class TestRowsInSitesOfEveryZone(StoreCase):
	def test_a_request_made_in_each_zone_is_stored_as_that_zones_wall_clock_and_comes_back_as_it_went_in(
		self,
	):
		for name in ZONES:
			with (
				self.subTest(zone=name),
				mock.patch.object(convert, "site_zone", lambda name=name: ZoneInfo(name)),
			):
				frappe.db.savepoint("zone")
				self.core.approvals.insert(
					"z1", "k", "{}", None, None, "2026-10-16T08:00:00+00:00", "2026-10-17T08:00:00.5+00:00"
				)
				stored = frappe.db.sql(
					"select created_at, expires_at from `tabMunimji Approval Request` where name='z1'",
					as_dict=True,
				)[0]
				expected = ZoneInfo(name)
				self.assertEqual(
					stored.created_at,
					datetime(2026, 10, 16, 8, 0, tzinfo=UTC).astimezone(expected).replace(tzinfo=None),
				)
				row = self.core.approvals.get("z1")
				self.assertEqual(
					(row["created_at"], row["expires_at"]),
					("2026-10-16T08:00:00+00:00", "2026-10-17T08:00:00.500000+00:00"),
				)
				self.assertEqual(self.core.approvals.due_for_expiry("2026-10-17T08:00:00.4+00:00"), [])
				self.assertEqual(self.core.approvals.due_for_expiry("2026-10-17T08:00:01+00:00"), ["z1"])
				frappe.db.rollback(save_point="zone")

	def test_a_filter_by_moment_means_the_same_moment_whatever_the_zone(self):
		for name in ("Asia/Kolkata", "America/New_York"):
			with (
				self.subTest(zone=name),
				mock.patch.object(convert, "site_zone", lambda name=name: ZoneInfo(name)),
			):
				frappe.db.savepoint("zone")
				for i, hour in enumerate((6, 8, 10)):
					self.core.approvals.insert(
						f"f{i}",
						"k",
						"{}",
						None,
						None,
						f"2026-10-16T{hour:02d}:00:00+00:00",
						f"2026-10-16T{hour:02d}:00:00+00:00",
					)
				self.assertEqual(
					sorted(self.core.approvals.due_for_expiry("2026-10-16T08:00:00+00:00")), ["f0", "f1"]
				)
				self.assertEqual(
					[
						r["id"]
						for r in self.core.approvals.search(
							[], None, None, "2026-10-16T08:00:00+00:00", None, 10
						)
					],
					["f2", "f1"],
				)
				frappe.db.rollback(save_point="zone")


class TestEmptyValuesAreNotMixedUp(StoreCase):
	def test_none_and_the_empty_string_stay_two_things(self):
		self.core.approvals.insert("e1", "k", "{}", None, None, "2026-10-16T08:00:00+00:00", None)
		self.core.approvals.insert("e2", "k", "{}", "", "", "2026-10-16T08:00:00+00:00", None)
		self.core.approvals.cancel_if_pending("e2", "")
		a, b = self.core.approvals.get("e1"), self.core.approvals.get("e2")
		self.assertEqual(
			(a["ref_type"], a["ref_id"], a["status_note"], a["expires_at"], a["decision_json"]),
			(None, None, None, None, None),
		)
		self.assertEqual((b["ref_type"], b["ref_id"], b["status_note"]), ("", "", ""))

	def test_a_number_that_is_none_is_not_zero(self):
		s = self.stock.proposals
		s.insert(
			"n", "w", "BOLT", "awaiting", None, None, None, None, None, None, "", "2026-10-16T08:00:00+00:00"
		)
		s.insert(
			"z", "w", "BOLT", "awaiting", None, None, 0.0, 0.0, 0.0, None, "", "2026-10-16T08:00:00+00:00"
		)
		none, zero = s.get("n"), s.get("z")
		self.assertEqual((none["qty"], none["rate"], none["total"]), (None, None, None))
		self.assertEqual((zero["qty"], zero["rate"], zero["total"]), (0.0, 0.0, 0.0))
		s.revise("z", None, None, None, 4.5, None, "", "2026-10-16T09:00:00+00:00")
		self.assertEqual((s.get("z")["qty"], s.get("z")["rate"], s.get("z")["total"]), (None, 4.5, None))
		s.revise("z", "S1", "Acme", 0.0, 4.5, 0.0, "", "2026-10-16T09:00:00+00:00")
		self.assertEqual((s.get("z")["qty"], s.get("z")["total"]), (0.0, 0.0))

	def test_a_job_that_has_not_ended_has_no_result_not_a_failed_one(self):
		self.core.jobs.started("check", "2026-10-16T08:00:00+00:00")
		row = self.core.jobs.get("check")
		self.assertEqual((row["last_ok"], row["last_end"], row["last_error"]), (None, None, None))


class TestLongAndAwkwardText(StoreCase):
	def test_two_megabytes_of_reasoning_and_of_request_come_back_whole_and_can_be_searched(self):
		why = ("Because the stock is low. " * 80_000) + "the very last sentence"
		self.stock.alerts.insert("big", "BOLT", "BREACH", 2, "2026-10-16T08:00:00+00:00", "{}", why, None)
		self.assertEqual(self.stock.alerts.get("big")["reasoning_text"], why)
		request = '{"title":"big","why":"' + ("x" * 2_000_000) + 'needle"}'
		self.core.approvals.insert("big", "k", request, None, None, "2026-10-16T08:00:00+00:00", None)
		self.assertEqual(self.core.approvals.get("big")["request_json"], request)
		self.assertEqual(
			[r["id"] for r in self.core.approvals.search(["NEEDLE"], None, None, None, None, 5)], ["big"]
		)

	def test_json_text_is_kept_byte_for_byte(self):
		text = '{"z": 1,  "a": "é\\u2028 日本語 ✓ 🙂", "m": [3, 2, 1],\n "tax": 1.10}'
		self.core.approvals.insert("j", "k", text, None, None, "2026-10-16T08:00:00+00:00", None)
		self.core.approvals.decide_if_pending("j", text, "2026-10-16T09:00:00+00:00")
		row = self.core.approvals.get("j")
		self.assertEqual((row["request_json"], row["decision_json"]), (text, text))

	def test_the_tables_that_keep_their_whole_row_keep_it_whole(self):
		self.core.agents.add_task(
			"t",
			"inventory",
			"brief",
			"2026-10-16T08:00:00+00:00",
			"llama3.1",
			"ollama",
			False,
			None,
			"priya",
			"what is low? é 日本語",
		)
		trace = '[{"m": 1}]' * 50_000
		self.core.agents.finish_task(
			"t", "ok", "2026-10-16T08:01:00+00:00", '{"a": 1}', "fine " * 3000, 3, 2, 1.5, 100, 40, trace
		)
		row = self.core.agents.get("t")
		self.assertEqual(
			(row["request_text"], row["trace_json"], row["note"], row["llm_seconds"]),
			("what is low? é 日本語", trace, "fine " * 3000, 1.5),
		)


class TestNames(StoreCase):
	def test_ids_that_come_from_outside_are_kept_apart_however_they_differ(self):
		inbound = self.core.inbound
		for external in ("wamid.HBgLAbC", "wamid.hbglabc", "wamid.HBgLAbC ", "x" * 500, "ä", "a"):
			self.assertTrue(inbound.claim("whatsapp", external, "2026-10-16T08:00:00+00:00"), external)
		self.assertFalse(inbound.claim("whatsapp", "wamid.HBgLAbC", "2026-10-16T09:00:00+00:00"))
		self.assertFalse(inbound.claim("whatsapp", "x" * 500, "2026-10-16T09:00:00+00:00"))
		self.assertTrue(
			inbound.claim("telegram", "wamid.HBgLAbC", "2026-10-16T09:00:00+00:00"),
			"another channel's ids are its own",
		)

	def test_an_id_the_engine_made_that_the_database_cannot_name_a_record_with_is_refused(self):
		for bad in ("", " a1", "a1 ", "a<1>", "x" * 141):
			with self.subTest(bad=bad[:12]), self.assertRaises(ValueError):
				self.core.approvals.insert(bad, "k", "{}", None, None, "2026-10-16T08:00:00+00:00", None)
		self.core.approvals.insert("x" * 140, "k", "{}", None, None, "2026-10-16T08:00:00+00:00", None)
		self.assertEqual(self.core.approvals.get("x" * 140)["id"], "x" * 140)

	def test_numbers_are_rolled_back_with_the_transaction_as_they_are_on_sqlite(self):
		a = self.core.agents
		with self.assertRaises(RuntimeError), self.core.transaction():
			a.add_tool_call("2026-10-16T08:00:00+00:00", "agent", "mcp", "t", "{}", True, 1, None, None)
			raise RuntimeError("the handler failed")
		a.add_tool_call("2026-10-16T09:00:00+00:00", "agent", "mcp", "t", "{}", True, 1, None, None)
		self.assertEqual([r["id"] for r in a.tool_calls(None, 10)], [1])


class TestWhereTheDocTypesDifferFromSqlite(StoreCase):
	"""Each of these is a place where the answer is not what SQLite gives. All of them follow from how MariaDB and Frappe hold a record; each is explained in docs/STORES.md."""

	def test_names_and_item_codes_are_compared_ignoring_case_and_accents_as_erpnext_does(self):
		s = self.stock.alerts
		s.insert("a1", "BOLT", "BREACH", 1, "2026-10-16T08:00:00+00:00", "{}", "", None)
		self.assertEqual(
			s.latest_for_item("bolt")["id"],
			"a1",
			"SQLite would say there is none: an item is the same item whatever case it is typed in, in ERPNext",
		)
		self.assertIsNotNone(s.latest_for_item("BÖLT"), "and ignoring accents")
		with self.assertRaises(Exists):  # and an id that differs only in case is the same id
			s.insert("A1", "BOLT", "BREACH", 1, "2026-10-16T08:00:00+00:00", "{}", "", None)

	def test_a_text_that_is_not_json_is_refused_in_a_json_column(self):
		with self.assertRaises(Exception):
			self.core.approvals.insert("x", "k", "not json", None, None, "2026-10-16T08:00:00+00:00", None)

	def test_a_short_column_refuses_a_value_of_more_than_140_characters(self):
		with self.assertRaises(frappe.ValidationError):
			self.core.approvals.insert("long", "k" * 141, "{}", None, None, "2026-10-16T08:00:00+00:00", None)

	def test_a_moment_with_another_offset_comes_back_as_utc(self):
		self.core.approvals.insert("o", "k", "{}", None, None, "2026-10-16T13:30:00+05:30", None)
		self.assertEqual(self.core.approvals.get("o")["created_at"], "2026-10-16T08:00:00+00:00")
