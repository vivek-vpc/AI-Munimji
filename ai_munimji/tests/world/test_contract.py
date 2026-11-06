"""The shared ERP-client checks (ai_munimji_engine.testkit.contract), the very ones the standalone service's demo ERP and REST client are held to, run on the Frappe client.

As Administrator every check must pass: the Frappe client gives the same answers as the other two on the same data. For a restricted person a check may fail only because the ERP
refuses that person something; test_permissions.py pins which person gets what, and the report in docs/ERP_CLIENT_COMPARISON.md lists the checks one by one."""

from ai_munimji_engine.testkit import contract

from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.tests.world import WorldCase, as_user, discard, submit


class TestSharedChecks(WorldCase):
	def run_checks(self, user: str, only: set[str] | None = None) -> list[contract.Result]:
		site = contract.Site(today=self.today, names=self.names, submit=submit, discard=discard)
		with as_user(user):
			return contract.run_checks(FrappeERPClient(), site, only=only)

	def test_as_administrator_every_check_passes(self):
		results = self.run_checks("Administrator")
		self.assertEqual([(r.name, r.status, r.detail) for r in results if r.status != "pass"], [])
		self.assertEqual(len(results), len(contract.CHECKS), "a check was left out of the run")
		self.assertGreaterEqual(len(results), 40)

	def test_the_checks_that_write_leave_nothing_submitted(self):
		results = self.run_checks("Administrator", only={c.name for c in contract.CHECKS if c.writes})
		self.assertTrue(results)
		self.assertEqual([(r.name, r.status) for r in results if r.status != "pass"], [])

	def test_a_person_with_the_roles_the_install_notes_name_passes_what_those_roles_may_read(self):
		results = self.run_checks("approver")
		failed = {r.name for r in results if r.status != "pass"}
		# the approver (Purchase User + Stock User) reads stock and purchasing; what fails is only what needs a right they do not have (see test_permissions.py for which)
		self.assertTrue(
			failed
			<= {r.name for r in results if "ermission" in r.detail or "not permitted" in r.detail.lower()},
			failed,
		)
