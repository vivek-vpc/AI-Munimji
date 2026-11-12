"""Tests that need the contract world: the small, fixed set of warehouses, items, suppliers, orders and tax rules that the shared ERP-client checks of ai-munimji-engine are written
against (`ai_munimji_engine.testkit.world`). They run the real FrappeERPClient on a real site, as real users.

The world is loaded into the development site by `dev/scripts/load_contract_world.py` and described in `dev/contract-site.json`. On a site that does not hold it (the test site that
`bench run-tests` uses) these tests are skipped, and say so. Run them where the world is:   .\\dev\\world-tests.ps1

Every test cleans up after itself: the users it makes and the documents it creates are removed, and the run ends with a rollback. The two kinds of test that need other database connections to
see their data (test_parallel_presses.py, test_end_to_end.py) commit what they set up, and remove it, and empty the app's own records, when they are done.
"""

import json
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import frappe

from ai_munimji.tests.helpers import make_user

SITE_FILE = Path(__file__).resolve().parents[3] / "dev" / "contract-site.json"

# the people the permission tests speak of. The ERPNext roles are the ones docs/INSTALL.md names, with the app role that goes with the job (the app's own records need it); "neither" has only
# the app's Viewer role, which reads nothing of ERPNext's, and "nobody" has no role at all.
PEOPLE = {
	"viewer": ("world.viewer@example.com", ("Stock User", "Munimji Viewer")),
	"approver": ("world.approver@example.com", ("Purchase User", "Stock User", "Munimji Approver")),
	"manager": ("world.manager@example.com", ("Stock User", "Munimji Manager")),
	"neither": ("world.neither@example.com", ("Munimji Viewer",)),
	"nobody": ("world.nobody@example.com", ()),
}


def described() -> dict | None:
	try:
		return json.loads(SITE_FILE.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return None


@contextmanager
def as_user(user: str):
	"""Everything inside is done as this user (a name from PEOPLE is looked up)."""
	who = frappe.session.user
	frappe.set_user(PEOPLE[user][0] if user in PEOPLE else user)
	try:
		yield
	finally:
		frappe.set_user(who)


@contextmanager
def as_administrator():
	with as_user("Administrator"):
		yield


STOCK_CHECK_JOB = "ai_munimji.jobs.run_stock_check"


@contextmanager
def queue_captured():
	"""What the code under test puts on the queue is noted, as (method, options), and not queued: CI has no worker, and on a developer's bench a worker would run the job beside the test.
	A call with now=True is a call that Frappe makes at once (the notification logs, when frappe.in_test is set); it goes through. Threads share it, so a test that runs ticks on several
	connections patches once, around all of them."""
	queued: list[tuple[str, dict]] = []
	real_enqueue = frappe.enqueue

	def capture(method, **options):
		if options.get("now"):
			return real_enqueue(method, **options)
		queued.append((method, options))

	with mock.patch.object(frappe, "enqueue", capture):
		yield queued


def scheduled_tick(job_type, queued: list) -> list[str]:
	"""What the scheduler does with the stock check when it is due, and what a worker then does with what that queued. The job record runs `jobs.check_stock`, which only puts the run on the long
	queue and returns (so that the scheduler is not held up for the length of a run); the run itself is a queued job, so it is run here the way a worker runs it, as Administrator (the jobs of this
	app switch to the system mode themselves). `queued` is the list `queue_captured` gave; only what this tick queued is run. Returns the methods that were run."""
	first = len(queued)
	with as_administrator():
		job_type.execute()
	ran = []
	for method, _options in queued[first:]:
		if method == STOCK_CHECK_JOB:
			with as_administrator():
				frappe.get_attr(method)()
			ran.append(method)
	frappe.db.commit()  # a worker commits a job that returns
	return ran


class WorldCase(unittest.TestCase):
	"""A test case on the contract world. `self.names` are the names the site gave the world's parts (self.names["steady"] is an item code), `self.today` is the reference day the world's
	dates are relative to, `self.person(key)` is the email of one of PEOPLE."""

	@classmethod
	def setUpClass(cls):
		info = described()
		if info is None:
			raise unittest.SkipTest(
				"the contract world is not described here (dev/contract-site.json): load it with dev/scripts/load_contract_world.py"
			)
		cls.names, cls.today = info["names"], date.fromisoformat(info["today"])
		cls.company, cls.abbr = info["company"], info["abbr"]
		if not frappe.db.exists("Item", cls.names["steady"]):
			raise unittest.SkipTest(
				f"the contract world is not loaded on {frappe.local.site}: load it with dev/scripts/load_contract_world.py"
			)
		frappe.set_user("Administrator")
		cls.users = {key: make_user(email, roles) for key, (email, roles) in PEOPLE.items()}
		cls.made = []  # (doctype, name) of what the tests created, removed in tearDownClass

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for doctype, name in reversed(getattr(cls, "made", [])):
			discard(doctype, name)
		for email in getattr(cls, "users", {}).values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.rollback()

	def person(self, key: str) -> str:
		return self.users[key]

	def remember(self, doctype: str, name: str) -> str:
		self.made.append((doctype, name))
		return name

	def required_by(self, days: int = 14) -> date:
		return self.today + timedelta(days=days)


def discard(doctype: str, name: str) -> None:
	"""Remove a document the tests made, whatever its state (a submitted one is cancelled first)."""
	with as_administrator():
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


def submit(doctype: str, name: str) -> None:
	"""Submit a draft as Administrator (the client itself never submits)."""
	with as_administrator():
		frappe.get_doc(doctype, name).submit()
