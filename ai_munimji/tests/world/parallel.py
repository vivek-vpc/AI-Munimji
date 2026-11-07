"""Run work on several real database connections at once.

A test that is rolled back at its end cannot show a race: the other connections never see its rows. These tests commit what they set up and what they make, and remove it again
(`ParallelCase` below), so that two presses of one button really do arrive as two transactions, as they do from two workers or two servers.
"""

import threading
from collections.abc import Callable
from typing import Any

import frappe

from ai_munimji.tests.world import WorldCase, as_administrator, discard


def on_own_connections(user: str, jobs: list[Callable[[], Any]], timeout: float = 90.0) -> list[Any]:
	"""Run each job on its own thread with its own connection, signed in as `user`; all start together once every connection is ready. A job's database work is committed when it returns
	and rolled back when it raises. Returns, per job, what it returned or the exception it raised."""
	site, sites_path = frappe.local.site, frappe.local.sites_path
	ready = threading.Barrier(len(jobs))
	results: list[Any] = [None] * len(jobs)

	def run(index: int, job: Callable[[], Any]) -> None:
		try:
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user(user)
			ready.wait(timeout)
			try:
				results[index] = job()
				frappe.db.commit()
			except BaseException as exc:
				frappe.db.rollback()
				results[index] = exc
		except BaseException as exc:
			results[index] = exc
		finally:
			frappe.destroy()

	threads = [threading.Thread(target=run, args=(i, job), daemon=True) for i, job in enumerate(jobs)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join(timeout)
	hung = [i for i, thread in enumerate(threads) if thread.is_alive()]
	if hung:
		raise AssertionError(f"jobs {hung} did not finish within {timeout} seconds")
	return results


class ParallelCase(WorldCase):
	"""A world case whose setup is committed (the other connections must see the users) and whose clean-up is committed too."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.commit()

	ref_prefix = "WT-par"  # every reference these tests use starts with it, so that a test that failed half way still leaves nothing behind

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.commit()
		for doctype in ("Purchase Order", "Material Request", "Stock Entry"):
			for row in frappe.get_all(
				doctype, filters={"custom_agent_ref": ["like", f"{cls.ref_prefix}%"]}, pluck="name"
			):
				discard(doctype, row)
		for doctype, name in reversed(getattr(cls, "made", [])):
			discard(doctype, name)
		for email in getattr(cls, "users", {}).values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()

	def seen_by_everyone(self) -> None:
		"""End this connection's snapshot, so that what the other connections committed can be read."""
		frappe.db.commit()

	def committed_documents(self, doctype: str, filters: dict) -> list[dict]:
		self.seen_by_everyone()
		with as_administrator():
			return frappe.get_all(doctype, filters=filters, fields=["name", "docstatus"], order_by="creation")
