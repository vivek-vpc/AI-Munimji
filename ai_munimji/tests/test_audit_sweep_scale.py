"""The audit sweep costs what is new, not the length of the history (finding A3 of the production-readiness review).

Before: every sweep fetched every sealed request id and every closed request, and every sealed settings change, into Python, to find the few that were new. Now a closed request carries the
app's own flag `sealed`, set when its entry is appended, and the sweep asks for the closed requests that do not have it, a batch at a time. What is shown: a sweep with nothing new reads the same
handful of rows whether the history holds 50 requests or 3,000; a backlog is sealed a batch at a time, oldest first; a site whose flags are missing (restored from a backup that predates them) is
put right without sealing anything twice; and the patch that sets the flags on a site that was sealed before them does so.
"""

from unittest import mock

import frappe
from ai_munimji_engine.testkit import stores as k
from frappe.tests import IntegrationTestCase

from ai_munimji import wiring
from ai_munimji.patches import mark_the_sealed_records
from ai_munimji.stores import frappe_core_stores
from ai_munimji.tests.helpers import FakeStock, empty_store_tables, insert_sealed_history

APPROVALS, SEAL, CHANGES = "Munimji Approval Request", "Munimji Audit Seal", "Munimji Settings Change"


class Reads:
	"""Counts what `frappe.get_list` returns while it is in force."""

	def __enter__(self):
		self.rows, self.queries, real = 0, 0, frappe.get_list

		def counting(*args, **kwargs):
			got = real(*args, **kwargs)
			self.rows += len(got)
			self.queries += 1
			return got

		self._patch = mock.patch.object(frappe, "get_list", counting)
		self._patch.start()
		return self

	def __exit__(self, *exc):
		self._patch.stop()


class SweepCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"sweep_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = frappe_core_stores(system=True)
		self.audit = wiring.build(FakeStock(1), self.core).audit

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)


class TestASweepWithNothingNewReadsAHandfulOfRows(SweepCase):
	def read_by_an_empty_sweep(self) -> tuple[int, int]:
		with Reads() as reads:
			self.assertEqual(self.audit.sweep(), 0)
		return reads.rows, reads.queries

	def test_the_rows_read_do_not_depend_on_how_much_history_there_is(self):
		insert_sealed_history(50)
		small = self.read_by_an_empty_sweep()
		empty_store_tables()
		insert_sealed_history(3000)
		large = self.read_by_an_empty_sweep()
		self.assertEqual(large, small, "the same rows and queries over 3,000 sealed requests as over 50")
		self.assertLessEqual(large[0], 5, f"a handful of rows: {large}")
		self.assertLessEqual(large[1], 6, f"and a handful of queries: {large}")

	def test_the_chain_the_helper_writes_is_a_real_one(self):
		insert_sealed_history(300)
		self.assertTrue(
			self.audit.verify()["ok"], "the history these tests measure against passes the seal's own check"
		)
		self.assertEqual(self.core.audit.unsealed_count(), 0)

	def test_a_request_closed_after_a_long_history_is_sealed_and_nothing_else_is_read_for_it(self):
		insert_sealed_history(500)
		self.core.approvals.insert(
			"new-1", "procurement.po", "{}", None, None, "2026-12-01T08:00:00+00:00", None
		)
		self.core.approvals.decide_if_pending("new-1", '{"action": "approve"}', "2026-12-01T09:00:00+00:00")
		with Reads() as reads:
			self.assertEqual(self.audit.sweep(), 1)
		self.assertLessEqual(reads.rows, 10, f"{reads.rows} rows for one new request over a history of 500")
		self.assertEqual(self.core.audit.entries()[-1]["ref_id"], "new-1")
		self.assertTrue(self.audit.verify()["ok"])


class TestABacklogIsSealedABatchAtATime(SweepCase):
	def closed(self, n: int):
		for i in range(n):
			self.core.approvals.insert(
				f"b-{i}", "procurement.po", "{}", None, None, f"2026-10-16T08:{i:02d}:00+00:00", None
			)
			self.core.approvals.decide_if_pending(
				f"b-{i}", '{"action": "approve"}', f"2026-10-16T09:{i:02d}:00+00:00"
			)

	def test_a_sweep_seals_at_most_one_batch_oldest_first(self):
		self.closed(7)
		with mock.patch("ai_munimji.stores.core.SEAL_BATCH", 3):
			self.assertEqual(self.audit.sweep(), 3)
			self.assertEqual([e["ref_id"] for e in self.core.audit.entries()], ["b-0", "b-1", "b-2"])
			self.assertEqual(self.core.audit.unsealed_count(), 4)
			self.assertEqual(self.audit.sweep(), 3)
			self.assertEqual(self.audit.sweep(), 1)
			self.assertEqual(self.audit.sweep(), 0)
		self.assertEqual([e["ref_id"] for e in self.core.audit.entries()], [f"b-{i}" for i in range(7)])
		self.assertTrue(self.audit.verify()["ok"])

	def test_a_request_is_flagged_when_it_is_sealed_and_a_pending_one_is_not(self):
		self.closed(2)
		self.core.approvals.insert(
			"open", "procurement.po", "{}", None, None, "2026-10-16T08:59:00+00:00", None
		)
		self.audit.sweep()
		flags = dict(frappe.db.sql(f"SELECT name, sealed FROM `tab{APPROVALS}`"))
		self.assertEqual(flags, {"b-0": 1, "b-1": 1, "open": 0})


class TestSitesWhoseFlagsAreMissing(SweepCase):
	def sealed_history(self):
		chain = k.audit_history(self.core)
		self.assertEqual(chain.sweep(), 4)
		return chain

	def forget_the_flags(self):
		frappe.db.sql(f"UPDATE `tab{APPROVALS}` SET sealed = 0")
		frappe.db.sql(f"UPDATE `tab{CHANGES}` SET sealed = 0")

	def test_a_sweep_puts_missing_flags_right_and_seals_nothing_twice(self):
		chain = self.sealed_history()
		before = [e["hash"] for e in self.core.audit.entries()]
		self.forget_the_flags()
		self.assertEqual(self.core.audit.unsealed_count(), 2, "the two closed requests look unsealed")
		self.assertEqual(chain.sweep(), 0, "but the chain holds their entries: nothing is sealed again")
		self.assertEqual([e["hash"] for e in self.core.audit.entries()], before)
		self.assertEqual(self.core.audit.unsealed_count(), 0, "and the flags are right again")
		self.assertEqual(chain.sweep(), 0)
		self.assertTrue(chain.verify()["ok"])

	def test_the_settings_changes_too(self):
		chain = self.sealed_history()
		self.forget_the_flags()
		self.assertEqual(self.core.audit.last_sealed_setting(), 0, "no flag, so none is known to be sealed")
		self.assertEqual(chain.sweep(), 0)
		self.assertEqual(self.core.audit.last_sealed_setting(), 2, "found out from the chain, flagged again")
		self.assertEqual(len(self.core.audit.entries()), 4)

	def test_the_patch_flags_what_the_chain_already_holds_and_runs_again_without_changing_anything(self):
		chain = self.sealed_history()
		self.forget_the_flags()
		mark_the_sealed_records.execute()
		self.assertEqual(self.core.audit.unsealed_count(), 0)
		self.assertEqual(self.core.audit.last_sealed_setting(), 2)
		flags = frappe.db.sql(f"SELECT name, sealed FROM `tab{APPROVALS}` ORDER BY name")
		mark_the_sealed_records.execute()
		self.assertEqual(frappe.db.sql(f"SELECT name, sealed FROM `tab{APPROVALS}` ORDER BY name"), flags)
		self.assertEqual(
			sorted(n for n, sealed in flags if sealed), ["a1", "a2"], "the open request a3 is not flagged"
		)
		self.assertTrue(chain.verify()["ok"])
