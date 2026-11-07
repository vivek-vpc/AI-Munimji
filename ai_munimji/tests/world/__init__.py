"""Tests that need the contract world: the small, fixed set of warehouses, items, suppliers, orders and tax rules that the shared ERP-client checks of ai-munimji-engine are written
against (`ai_munimji_engine.testkit.world`). They run the real FrappeERPClient on a real site, as real users.

The world is loaded into the development site by `dev/scripts/load_contract_world.py` and described in `dev/contract-site.json`. On a site that does not hold it (the test site that
`bench run-tests` uses) these tests are skipped, and say so. Run them where the world is:   .\\dev\\world-tests.ps1

Every test cleans up after itself: the users it makes and the documents it creates are removed, and the run ends with a rollback.
"""

import json
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

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
