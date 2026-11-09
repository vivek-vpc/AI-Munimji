"""The engine's 60 store checks, run on the DocType stores.

The same functions `erpnext-ai-agents` runs on SQLite and on memory (`ai_munimji_engine.testkit.stores`), run here on this site's DocTypes as Administrator in the named system mode (the
checks append to the audit seal, which only the scheduled job may do). Each check gets empty tables, and leaves them as it found them: the tables are emptied inside the test's transaction
and everything is rolled back at the end, so a site that already holds records is not touched.

Where a DocType store cannot be identical to the SQLite one, the check is not skipped: `DIFFERENCES` names the check, says why, and the test asserts the difference that was found, so that
a difference which grows, or one that disappears, makes this file fail (docs/STORES.md has the table).
"""

import frappe
from ai_munimji_engine.testkit import stores as store_checks
from frappe.tests import IntegrationTestCase

from ai_munimji.stores import frappe_core_stores, frappe_stock_stores
from ai_munimji.tests.helpers import empty_store_tables

# check name -> why the DocType stores differ from SQLite there (filled in as found; empty means all 60 are identical)
DIFFERENCES: dict[str, str] = {}


class TestStoresOnDocTypes(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"contract_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = frappe_core_stores(system=True)
		self.stock = frappe_stock_stores(self.core)

	def tearDown(self):
		frappe.db.rollback(save_point=self.savepoint)


def make_test(check):
	def run(self):
		check.run(self.core, self.stock)

	run.__name__ = f"test_{check.name}"
	run.__doc__ = check.name.replace("_", " ")
	return run


for _check in store_checks.CHECKS:
	setattr(TestStoresOnDocTypes, f"test_{_check.name}", make_test(_check))


class TestTheCheckList(IntegrationTestCase):
	def test_there_are_sixty_checks_and_all_of_them_are_run_here(self):
		names = {c.name for c in store_checks.CHECKS}
		self.assertEqual(len(names), 60)
		ran = {n[len("test_") :] for n in dir(TestStoresOnDocTypes) if n.startswith("test_")}
		self.assertEqual(ran, names)
