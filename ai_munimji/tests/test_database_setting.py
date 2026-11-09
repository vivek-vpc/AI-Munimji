"""The database runs MariaDB the way Frappe's own deployments run it, which the app's locks depend on.

MariaDB 11.8 (its stock image has the setting ON) refuses a locking read of a row that another connection changed after the transaction's snapshot (error 1020, "Record has changed
since last read") unless `innodb_snapshot_isolation` is OFF. The row locks that keep two presses of one button to one order, and the lease that keeps two runs of the job to one proposal, are locking reads, so
with the setting ON they fail under contention instead of waiting. Frappe's own Docker files (frappe_docker: pwd.yml and every MariaDB override) and its Pilot set it OFF, as dev/compose.yml does.
This test says so in one place, so that a database set up differently shows as this message and not as six failures in the concurrency tests.
"""

import frappe
from frappe.tests import IntegrationTestCase

VARIABLE = "innodb_snapshot_isolation"


class TestTheDatabaseSetting(IntegrationTestCase):
	def test_snapshot_isolation_is_off_as_in_frappes_own_deployments(self):
		rows = frappe.db.sql("SHOW VARIABLES LIKE %s", (VARIABLE,))
		if not rows:
			self.skipTest(
				f"this database has no {VARIABLE} (an older MariaDB, or MySQL): it does not refuse a locking read this way"
			)
		value = str(rows[0][1]).upper()
		self.assertIn(
			value,
			{"OFF", "0"},
			f"{VARIABLE} is {value}. AI Munimji needs it OFF: with it ON a locking read of a row that another connection changed since the transaction began fails with "
			"error 1020, so parallel presses and parallel runs of the job fail instead of waiting. Set `innodb_snapshot_isolation = OFF` in the server's [mysqld] section "
			"(or start it with --innodb-snapshot-isolation=OFF, as frappe_docker does); on a running server, `SET GLOBAL innodb_snapshot_isolation=OFF` is read by new connections.",
		)
