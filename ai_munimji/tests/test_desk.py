"""The app's place on the Desk (Frappe 16): the tile on the apps screen, the rail behind it, the module's sidebar and the home page with its shortcuts.

They are four files that have to agree (hooks.py, ai_munimji/dock/, ai_munimji/ai_munimji/sidebar/, ai_munimji/ai_munimji/workspace/), and Frappe says nothing when they do not: a shortcut that
names a field that is not there simply shows an empty list. So the first class reads the files, and the second asks a real site what each person is shown."""

import json
import unittest
from pathlib import Path

import frappe
from ai_munimji_engine.packs.stock_procurement.inventory.alerts import ACTIVE as ALERT_ACTIVE
from erpnext.tests.utils import ERPNextTestSuite
from frappe.boot import get_bootinfo

from ai_munimji import hooks
from ai_munimji.permissions import APP_ROLES, check_app_permission
from ai_munimji.stores import frappe_core_stores
from ai_munimji.tests.helpers import APPROVER_ROLES, empty_store_tables, make_request, make_user

PACKAGE = Path(__file__).resolve().parents[1]
WORKSPACE_FILE = PACKAGE / "ai_munimji" / "workspace" / "ai_munimji" / "ai_munimji.json"
SIDEBAR_FILE = PACKAGE / "ai_munimji" / "sidebar" / "ai_munimji" / "ai_munimji.json"
DOCK_FILE = PACKAGE / "dock" / "ai_munimji" / "ai_munimji.json"

NAME, MODULE, APP = "AI Munimji", "AI Munimji", "ai_munimji"
REQUEST, ALERT, SETTINGS = "Munimji Approval Request", "Munimji Stock Alert", "AI Munimji Settings"
# the row of the sidebar that is the shortcut of the same name on the home page, where the names differ
SIDEBAR_NAME = {SETTINGS: "Settings"}
OPERATORS = {"=", "!=", "in", "not in", "is", "like", "not like", ">", "<", ">=", "<="}
STANDARD_FIELDS = {"name", "docstatus", "owner", "creation", "modified"}


def load(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def conditions(text: str) -> list[list]:
	"""The filters of a shortcut or a sidebar row: a JSON list of [doctype, field, operator, value], or nothing."""
	return json.loads(text) if text else []


class TestTheFilesAgree(unittest.TestCase):
	def setUp(self):
		self.workspace, self.sidebar, self.dock = load(WORKSPACE_FILE), load(SIDEBAR_FILE), load(DOCK_FILE)

	def test_the_three_files_are_one_place_on_the_desk(self):
		w, s, d = self.workspace, self.sidebar, self.dock
		self.assertEqual((w["doctype"], w["name"], w["label"], w["title"]), ("Workspace", NAME, NAME, NAME))
		self.assertEqual((w["module"], w["public"], w["standard"]), (MODULE, 1, 1))
		self.assertEqual(
			(s["doctype"], s["name"], s["module"], s["app"], s["standard"]), ("Sidebar", NAME, MODULE, APP, 1)
		)
		# Frappe deletes a standard record whose file it cannot find at the next migrate: the file's name is the record's name
		self.assertEqual(
			(d["doctype"], d["name"], d["app"], d["standard"], d["user"]), ("Dock", APP, APP, 1, "")
		)
		self.assertEqual(
			[(row["link_type"], row["link_to"], row["title"]) for row in d["items"]],
			[("Sidebar", s["name"], NAME)],
		)
		self.assertTrue(d["items"][0]["icon"], "a row on the app's own dock needs an icon")

	def test_the_home_page_shows_every_shortcut_it_has_exactly_once(self):
		blocks = json.loads(self.workspace["content"])
		shown = [b["data"]["shortcut_name"] for b in blocks if b["type"] == "shortcut"]
		labels = [s["label"] for s in self.workspace["shortcuts"]]
		self.assertEqual(len(set(labels)), len(labels), "two shortcuts of one name")
		self.assertEqual(sorted(shown), sorted(labels))
		ids = [b["id"] for b in blocks]
		self.assertEqual(len(set(ids)), len(ids), "two blocks of one id")

	def test_the_home_page_is_for_the_people_who_are_shown_the_tile(self):
		self.assertEqual({r["role"] for r in self.workspace["roles"]}, set(APP_ROLES))

	def test_every_filtered_view_of_the_home_page_is_in_the_sidebar_with_the_same_filter(self):
		rows = {r["label"]: r for r in self.sidebar["items"] if r["type"] == "Link"}
		for shortcut in self.workspace["shortcuts"]:
			row = rows[SIDEBAR_NAME.get(shortcut["label"], shortcut["label"])]
			self.assertEqual(row["link_to"], shortcut["link_to"], shortcut["label"])
			self.assertEqual(
				conditions(row["filters"]), conditions(shortcut["stats_filter"]), shortcut["label"]
			)

	def test_the_sidebar_has_a_way_home_and_its_sections_are_filled(self):
		rows = self.sidebar["items"]
		self.assertEqual(
			(rows[0]["type"], rows[0]["link_type"], rows[0]["link_to"]), ("Link", "Workspace", NAME)
		)
		for index, row in enumerate(rows):
			if row["type"] == "Section Break":
				self.assertEqual(rows[index + 1].get("child"), 1, f"the section {row['label']!r} is empty")
			self.assertEqual(row.get("open_in_new_tab"), 0, row["label"])

	def test_the_apps_screen_entry_opens_the_home_page_and_has_its_logo(self):
		[entry] = hooks.add_to_apps_screen
		self.assertEqual(entry["name"], APP)
		self.assertEqual(entry["title"], NAME)
		self.assertEqual(entry["route"], "/desk/" + NAME.lower().replace(" ", "-"))
		self.assertEqual(entry["has_permission"], "ai_munimji.permissions.check_app_permission")
		logo = PACKAGE / "public" / "images" / entry["logo"].rsplit("/", 1)[-1]
		self.assertEqual(entry["logo"], f"/assets/{APP}/images/{logo.name}")
		self.assertTrue(logo.is_file(), logo)
		self.assertLess(
			logo.stat().st_size, 100_000, "the apps screen loads this for everyone: keep it small"
		)

	def test_the_logo_is_not_set_for_the_whole_navbar(self):
		# the last app to set app_logo_url takes over the navbar logo of the whole site
		self.assertFalse(hasattr(hooks, "app_logo_url"))


class TestWhatPeopleSeeOnTheDesk(ERPNextTestSuite):
	def setUp(self):
		self.viewer = make_user("munimji.viewer@example.com", ("Munimji Viewer",))
		self.approver = make_user("munimji.approver@example.com", APPROVER_ROLES)
		self.manager = make_user("munimji.manager@example.com", ("Munimji Manager",))
		self.sysmgr = make_user("munimji.sysmgr@example.com", ("System Manager",))
		self.stock_user = make_user("munimji.stock@example.com", ("Stock User", "Purchase User"))
		self.nobody = make_user("munimji.nobody@example.com", ())
		self.workspace, self.sidebar = load(WORKSPACE_FILE), load(SIDEBAR_FILE)

	def boot(self, user: str) -> dict:
		with self.set_user(user):
			frappe.clear_cache(user=user)
			return get_bootinfo()

	def test_every_filter_names_a_field_its_doctype_has_and_an_operator_frappe_knows(self):
		views = [(s["label"], s["link_to"], s["stats_filter"]) for s in self.workspace["shortcuts"]]
		views += [
			(r["label"], r["link_to"], r["filters"]) for r in self.sidebar["items"] if r["type"] == "Link"
		]
		for label, doctype, text in views:
			for filter_doctype, field, operator, value in conditions(text):
				where = f"{label}: {field}"
				self.assertEqual(filter_doctype, doctype, where)
				self.assertTrue(field in STANDARD_FIELDS or frappe.get_meta(doctype).has_field(field), where)
				self.assertIn(operator, OPERATORS, where)
				if doctype == ALERT and field == "status":
					self.assertIn(value, ALERT_ACTIVE, "the engine calls an alert that waits something else")

	def test_every_link_goes_to_something_that_exists(self):
		for row in self.sidebar["items"]:
			if row["type"] == "Link" and row["link_type"] == "DocType":
				self.assertTrue(frappe.db.exists("DocType", row["link_to"]), row["label"])
		for shortcut in self.workspace["shortcuts"]:
			self.assertTrue(frappe.db.exists("DocType", shortcut["link_to"]), shortcut["label"])

	def test_each_request_view_lists_the_requests_in_that_state_and_no_others(self):
		empty_store_tables()
		approvals = frappe_core_stores(system=True).approvals
		waiting = make_request("Waiting").name
		answered = make_request("Answered").name
		expired = make_request("Expired").name
		withdrawn = make_request("Withdrawn").name
		self.assertTrue(
			approvals.decide_if_pending(answered, '{"action": "approve"}', "2026-10-16T09:00:00+00:00")
		)
		self.assertTrue(approvals.expire_if_pending(expired))
		self.assertTrue(approvals.cancel_if_pending(withdrawn, "the item was deleted"))

		expected = {
			"Waiting for your answer": {waiting},
			"Answered requests": {answered},
			"Expired or withdrawn": {expired, withdrawn},
			"All requests": {waiting, answered, expired, withdrawn},
		}
		shortcuts = {s["label"]: s for s in self.workspace["shortcuts"]}
		for label, names in expected.items():
			got = frappe.get_list(REQUEST, filters=conditions(shortcuts[label]["stats_filter"]), pluck="name")
			self.assertEqual(set(got), names, label)

	def test_the_tile_is_shown_to_the_apps_people_and_nobody_else(self):
		for user, shown in (
			(self.viewer, True),
			(self.approver, True),
			(self.manager, True),
			(self.sysmgr, True),
			(self.stock_user, False),
			(self.nobody, False),
		):
			with self.set_user(user):
				self.assertEqual(check_app_permission(), shown, user)
			entry = next((a for a in self.boot(user).get("app_data", []) if a["app_name"] == APP), None)
			self.assertEqual(bool(entry and entry["on_apps_screen"]), shown, user)

	def test_each_person_is_shown_only_the_sidebar_rows_they_may_open(self):
		everything = {r["label"] for r in self.sidebar["items"] if r["type"] == "Link"}
		for user, hidden in (
			(
				self.viewer,
				{"Draft purchase orders", "Settings"},
			),  # no right on Purchase Order, none on the Settings
			(self.approver, {"Settings"}),
			(self.manager, {"Draft purchase orders"}),  # the Munimji roles alone give no Purchase Order
		):
			sidebar = self.boot(user)["module_sidebars"][NAME]
			shown = {r["label"] for r in sidebar["items"] if r["type"] == "Link"}
			self.assertEqual(shown, everything - hidden, user)
		self.assertNotIn(NAME, self.boot(self.nobody).get("module_sidebars", {}))
