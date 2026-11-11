"""The clean-up of the high-volume records deletes the logs and nothing a person answers, and never the audit seal.

Every table is seeded with records of many ages, including very old ones in the tables that must never lose anything; the clean-up runs; what is gone and what is left is checked by name.
"""

from datetime import UTC, datetime, timedelta
from unittest import mock

import frappe
from ai_munimji_engine.core.common import iso
from frappe.tests import IntegrationTestCase

from ai_munimji import jobs, retention
from ai_munimji.stores import frappe_stock_stores
from ai_munimji.stores.specs import TABLES
from ai_munimji.tests.helpers import empty_store_tables

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
THE_REAL_LOOK_AT_THE_QUEUE = retention.room_in_the_queue  # the tests below replace it, and one of them is about it


def ago(days: float) -> str:
	return iso(NOW - timedelta(days=days))


class TestTheCleanUp(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"retention_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = jobs.system_stores()
		self.stock = frappe_stock_stores(self.core)
		self.seed()
		# the clean-up commits after every batch; this test's own transaction (its savepoint, below) must not be committed
		self.commits = mock.patch.object(jobs, "commit").start()
		self.room = mock.patch.object(retention, "room_in_the_queue", return_value=True).start()  # the queue of the site the tests run on is not what they are about
		self.addCleanup(mock.patch.stopall)

	def tearDown(self):
		frappe.db.rollback(save_point=self.savepoint)

	def seed(self):
		c, s = self.core, self.stock
		for name, days in (("old", 100), ("new", 10)):
			c.agents.add_tool_call(ago(days), "agent", "mcp", f"tool-{name}", "{}", True, 1, None, None)
		for name, days in (("t-ancient", 400), ("t-old", 100), ("t-new", 1), ("t-stuck", 500)):
			c.agents.add_task(name, "inventory", "brief", ago(days), "m", "ollama", False, None, "priya", "?")
			if name != "t-stuck":
				c.agents.finish_task(name, "ok", ago(days), None, "", 1, 0, 0.1, 1, 1, '[{"m": 1}]')
		for name, days in (("r-old", 100), ("r-new", 1)):
			s.runs.add(name, "inventory", ago(days), ago(days), False, "{}")
		for who, days in (("old", 100), ("new", 1)):
			s.assistant.log_chat(who, ago(days), "q", "intent", "answered", "rules")
		for key, days in (("k-old", 200), ("k-new", 1)):
			s.assistant.put_answer(key, "req", "q", "{}", "m", "priya", ago(days))
		for message, days in (("m-old", 20), ("m-new", 1)):
			c.inbound.claim("whatsapp", message, ago(days))
		for message, days, closes in (
			("v-closed-old", 400, True),
			("v-open-old", 400, False),
			("v-closed-new", 5, True),
		):
			s.vendors.add_message(
				message,
				"chase",
				f"PO-{message}",
				"Acme",
				"whatsapp",
				f"hash-{message}",
				"hmac1",
				"sent",
				None,
				None,
				"priya",
				ago(days),
			)
			if closes:
				s.vendors.close_replies("chase", f"PO-{message}", ago(days))
		for message, days in (("v-closed-old", 400), ("v-closed-new", 5)):
			s.vendors.add_reply(
				message, "Acme", "chase", f"PO-{message}", "whatsapp", "ok", ago(days), 1, f"text-{message}"
			)
		# what must never go, however old
		c.approvals.insert("req-pending", "procurement.po", "{}", None, None, ago(1000), None)
		c.approvals.insert("req-answered", "procurement.po", "{}", None, None, ago(1000), None)
		c.approvals.decide_if_pending("req-answered", '{"action": "approve"}', ago(999))
		s.alerts.insert("alert", "BOLT", "BREACH", 2, ago(1000), "{}", "low", None)
		s.notices.insert("notice", "BOLT", "LOW", ago(1000), None)
		s.proposals.insert(
			"proposal", "w", "BOLT", "awaiting", None, None, None, None, None, None, "", ago(1000)
		)
		s.transfers.insert("transfer", "BOLT", 1.0, "Nos", "A", "B", None, "priya", ago(1000))
		s.chases.start("PO-1", "Acme", "BOLT", "2026-01-01", ago(1000), "req", ago(1000))
		s.receipts.add("GRN-1", "Acme", "clean", "[]", None, ago(1000))
		s.quotes.insert("q", "BOLT", 1.0, "Nos", "[]", "2026-01-01", "priya", ago(1000))
		s.counts.upsert_schedule("BOLT", "A", None, "2026-01-01", ago(1000))
		c.workorders.insert("wo", "REORDER_NEEDED", "{}", "", ago(1000))
		c.audit.append(ago(1000), "approval", "req-answered", "decided", "d", "0" * 64, "h")
		c.settings.save("item", "BOLT", '{"min_qty": 5}', "priya", ago(1000), [("min_qty", "null", "5")])
		c.jobs.started("stock_check", ago(1000))

	def count(self, doctype: str) -> int:
		return frappe.db.count(doctype)

	def left(self, engine_table: str) -> set[str]:
		table = self.core.backend.table(engine_table)
		return set(table.names())

	def test_the_logs_older_than_the_period_go_and_the_newer_stay(self):
		gone = retention.clean_up(keep_days=30, now=NOW)
		self.assertEqual(
			gone,
			{
				"task_traces_cleared": 1,  # t-old: t-ancient was deleted whole, before its trace was looked at
				"vendor_numbers_forgotten": 1,  # v-open-old: the closed ones lost theirs when they were closed
				"tool_calls": 1,
				"agent_runs": 1,
				"chat_log": 1,
				"agent_tasks": 1,  # only the one older than a year that is not still running
				"assistant_answers": 1,
				"vendor_messages": 1,
				"vendor_replies": 1,
				"inbound_seen": 1,
			},
		)
		self.assertEqual({r["tool"] for r in self.core.agents.tool_calls(None, 10)}, {"tool-new"})
		self.assertEqual(self.left("agent_runs"), {"r-new"})
		self.assertEqual([r["asked_by"] for r in self.stock.assistant.chats(10)], ["new"])
		self.assertEqual(
			self.left("agent_tasks"),
			{"t-old", "t-new", "t-stuck"},
			"a task older than a year goes; one that is still running never does",
		)
		self.assertIsNone(
			self.core.agents.get("t-old")["trace_json"], "the trace of an old task goes, the task stays"
		)
		self.assertIsNotNone(self.core.agents.get("t-new")["trace_json"])
		self.assertIsNone(self.stock.assistant.cached_answer("k-old"))
		self.assertIsNotNone(self.stock.assistant.cached_answer("k-new"))
		self.assertTrue(
			self.core.inbound.claim("whatsapp", "m-old", ago(0)),
			"the old id is forgotten, so a message coming again would be handled again (it is a fortnight old)",
		)
		self.assertFalse(self.core.inbound.claim("whatsapp", "m-new", ago(0)))
		self.assertEqual(
			self.stock.vendors.open_chase_refs(),
			{"PO-v-open-old"},
			"an open conversation is never deleted, however old",
		)
		self.assertEqual(self.left("vendor_messages"), {"v-open-old", "v-closed-new"})

	def test_nothing_a_person_answers_and_nothing_of_the_seal_is_touched_however_old(self):
		before = {t.doctype: self.count(t.doctype) for t in TABLES}
		retention.clean_up(keep_days=1, now=NOW)
		protected = [
			"Munimji Approval Request",
			"Munimji Stock Alert",
			"Munimji Stock Notice",
			"Munimji Purchase Proposal",
			"Munimji Stock Transfer",
			"Munimji Delivery Chase",
			"Munimji Receipt Check",
			"Munimji Quote Round",
			"Munimji Cycle Count",
			"Munimji Work Order",
			"Munimji Audit Seal",
			"Munimji Settings Override",
			"Munimji Settings Change",
			"Munimji Job Run",
			"Munimji Lock",
			"Munimji Approval Delivery",
			"Munimji Count Review",
		]
		for doctype in protected:
			self.assertEqual(self.count(doctype), before[doctype], f"{doctype} lost records to the clean-up")
		self.assertEqual({r["status"] for r in self.core.approvals.list(None, 10)}, {"pending", "decided"})

	def test_the_list_of_what_may_be_deleted_names_only_logs(self):
		allowed = {
			"tool_calls",
			"agent_runs",
			"chat_log",
			"agent_tasks",
			"assistant_answers",
			"vendor_messages",
			"vendor_replies",
			"inbound_seen",
		}
		self.assertEqual(set(retention.RULES), allowed)
		for engine_table in retention.RULES:
			spec = next(t for t in TABLES if t.engine == engine_table)
			self.assertNotIn(
				"a", "".join(spec.perms.values()), f"{spec.doctype} is something a person approves"
			)

	def test_zero_keeps_the_logs_but_the_fixed_periods_still_apply(self):
		gone = retention.clean_up(keep_days=0, now=NOW)
		self.assertNotIn("tool_calls", gone)
		self.assertNotIn("agent_runs", gone)
		self.assertNotIn("chat_log", gone)
		self.assertEqual(len(self.core.agents.tool_calls(None, 10)), 2)
		self.assertEqual(self.left("agent_runs"), {"r-old", "r-new"})
		self.assertEqual(gone["inbound_seen"], 1, "the id of a handled message is not a log to keep")

	def test_a_second_run_deletes_nothing_more(self):
		retention.clean_up(keep_days=30, now=NOW)
		again = retention.clean_up(keep_days=30, now=NOW)
		self.assertEqual({k: v for k, v in again.items() if v}, {})

	def test_without_a_number_it_is_ninety_days_and_a_negative_number_cannot_be_saved(self):
		frappe.db.delete("Singles", {"doctype": "AI Munimji Settings", "field": "keep_logs_days"})
		frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")
		gone = retention.clean_up(now=NOW)
		self.assertEqual(gone.get("tool_calls"), 1, "a tool call 100 days old is past the default 90")
		self.assertEqual(self.left("agent_runs"), {"r-new"})
		page = frappe.get_doc("AI Munimji Settings")
		page.keep_logs_days = -1
		with self.assertRaises(frappe.ValidationError):
			page.save()


class TestABacklogIsClearedInBatchesThatEachStay(IntegrationTestCase):
	"""A site that has never been cleaned up holds a backlog of any size. One transaction for all of it ran out of time and rolled back everything, every day (finding A4 of the
	production-readiness review). Now a run removes at most a cap, oldest first, in batches with a commit after each, and the next run goes on."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"backlog_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = jobs.system_stores()
		self.commits = mock.patch.object(jobs, "commit").start()
		self.room = mock.patch.object(retention, "room_in_the_queue", return_value=True).start()  # the queue of the site the tests run on is not what they are about
		self.addCleanup(mock.patch.stopall)
		for n in range(25):  # tool calls 100 days old and more, one a minute apart: number 0 is the oldest
			self.core.agents.add_tool_call(
				iso(NOW - timedelta(days=100, minutes=25 - n)),
				"agent",
				"mcp",
				f"tool-{n:02d}",
				"{}",
				True,
				1,
				None,
				None,
			)

	def tearDown(self):
		frappe.db.rollback(save_point=self.savepoint)

	def tools_left(self) -> list[str]:
		return sorted(r["tool"] for r in self.core.agents.tool_calls(None, 100))

	def test_a_run_removes_at_most_the_cap_and_the_oldest_first(self):
		gone = retention.clean_up(keep_days=90, now=NOW, cap=10, batch=4)
		self.assertEqual(gone["tool_calls"], 10)
		self.assertEqual(
			gone["left_for_the_next_run"],
			1,
			"it says that it stopped at the cap, and that one table (the tool calls) may hold more",
		)
		self.assertEqual(self.tools_left(), [f"tool-{n:02d}" for n in range(10, 25)], "the ten oldest went")

	def test_every_batch_is_committed_so_that_a_failure_takes_back_one_batch_at_most(self):
		retention.clean_up(keep_days=90, now=NOW, cap=10, batch=4)
		batches = self.commits.call_count
		self.assertGreaterEqual(
			batches, 3, "10 records in batches of 4: 4, 4 and 2, each followed by a commit"
		)

	def test_the_next_run_goes_on_and_a_run_with_nothing_left_removes_nothing(self):
		totals = []
		for _ in range(5):
			totals.append(retention.clean_up(keep_days=90, now=NOW, cap=10, batch=4).get("tool_calls", 0))
		self.assertEqual(
			totals, [10, 10, 5, 0, 0], "a backlog of 25 is gone after three runs, always making progress"
		)
		self.assertEqual(self.tools_left(), [])

	def test_a_run_that_fails_in_the_middle_keeps_the_batches_before_it(self):
		table = self.core.backend.table("tool_calls")
		real, seen = table.remove, []

		def remove_but_fail_on_the_tenth(name):
			seen.append(name)
			if len(seen) == 10:
				raise RuntimeError("the database went away")
			return real(name)

		with mock.patch.object(type(table), "remove", lambda self, name: remove_but_fail_on_the_tenth(name)):
			with self.assertRaises(RuntimeError):
				retention.clean_up(keep_days=90, now=NOW, cap=20, batch=4)
		self.assertEqual(
			self.commits.call_count, 2, "the first two batches of four were committed before the failure"
		)
		self.assertEqual(
			self.tools_left(), [f"tool-{n:02d}" for n in range(9, 25)], "nine went (it failed on the tenth)"
		)

	def test_no_table_is_starved_by_a_big_one(self):
		for n in range(10):
			self.core.inbound.claim("whatsapp", f"m-{n}", iso(NOW - timedelta(days=30, minutes=n)))
		gone = retention.clean_up(keep_days=90, now=NOW, cap=12, batch=4)
		self.assertEqual(
			(gone["tool_calls"], gone["inbound_seen"]),
			(8, 4),
			"the tables take turns: four of each, and again four of the tool calls",
		)

	def test_the_run_ends_when_the_workers_have_not_taken_the_jobs_the_deletions_queue_and_leaves_the_rest(self):
		with (
			mock.patch.object(retention, "room_in_the_queue", return_value=False),
			mock.patch.object(retention.time, "sleep") as slept,
		):
			gone = retention.clean_up(keep_days=90, now=NOW, cap=10, batch=4)
		self.assertEqual(gone["tool_calls"], 0, "nothing was deleted into a queue that could not take the jobs")
		self.assertEqual(gone["left_for_the_next_run"], len(retention.RULES), "no table was looked at: every one is left for the next run")
		self.assertEqual(slept.call_count, retention.QUEUE_WAIT_SECONDS, "it waited for the workers first")
		self.assertEqual(len(self.tools_left()), 25)

	def test_the_run_waits_for_the_workers_and_then_goes_on(self):
		answers = iter([False, False, True] + [True] * 50)
		with (
			mock.patch.object(retention, "room_in_the_queue", side_effect=lambda needed: next(answers)),
			mock.patch.object(retention.time, "sleep") as slept,
		):
			gone = retention.clean_up(keep_days=90, now=NOW, cap=10, batch=4)
		self.assertEqual(gone["tool_calls"], 10)
		self.assertEqual(slept.call_count, 2, "two looks found no room, the third did")

	def test_there_is_room_while_the_queue_plus_the_batch_stays_under_frappes_own_limit(self):
		for queued, wanted, room in ((300, 100, True), (450, 100, False), (0, 499, True), (0, 500, False)):
			with (
				mock.patch("frappe.utils.background_jobs.get_queue", return_value=mock.Mock(count=queued)),
				mock.patch("frappe.conf", frappe._dict(max_queued_jobs=500)),
			):
				self.assertEqual(
					THE_REAL_LOOK_AT_THE_QUEUE(wanted), room, f"{queued} queued, {wanted} to queue, limit 500"
				)
