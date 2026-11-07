import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji.install import ROLES
from ai_munimji.tests.helpers import make_user

DOCTYPE_DIR = Path(__file__).resolve().parents[1] / "ai_munimji" / "doctype"
MODULE = "AI Munimji"

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"
SEAL = "Munimji Audit Seal"

V, A, M, S = "Munimji Viewer", "Munimji Approver", "Munimji Manager", "System Manager"
# What a letter grants. Written here again, not read from ai_munimji/stores/specs.py: the files are made from the specs, and this test is what says the files are right.
RIGHTS = {
	"r": {"read"},
	"w": {"write"},
	"c": {"create"},
	"d": {"delete"},
	"x": {"report", "export"},
	"a": {"approve"},
}

# a screen a person looks at and answers: the Viewer reads, the Approver and the Manager answer, System Manager can do what the Manager does
SCREEN = {V: "rx", A: "rwcx", M: "rwcx", S: "rwcx"}
# THE rights, written out. Everything not listed for a role is NOT granted, including the rights that a permission row gives by default (write, create, delete, report, export,
# share, print, email). A new DocType of this app, or a role added to one, fails the tests below until it is listed here on purpose.
EXPECTED_LETTERS: dict[str, dict[str, str]] = {
	SETTINGS: {M: "rw", S: "rw"},
	REQUEST: {V: "rx", A: "rwcxa", M: "rwcxa", S: "rwcxa"},
	"Munimji Approval Delivery": {V: "r", A: "r", M: "r", S: "r"},
	SEAL: {
		M: "r",
		S: "r",
	},  # no role may write, create or delete a row of it; the scheduled job (Administrator) appends
	"Munimji Settings Override": {V: "r", A: "r", M: "rwcd", S: "rwcd"},
	"Munimji Settings Change": {M: "rc", S: "r"},
	"Munimji Work Order": SCREEN,
	"Munimji Agent Task": {A: "c", M: "rc", S: "r"},
	"Munimji Tool Call": {A: "c", M: "rc", S: "r"},
	"Munimji Job Run": {M: "r", S: "r"},
	"Munimji Inbound Seen": {M: "r", S: "r"},
	"Munimji Stock Alert": SCREEN,
	"Munimji Stock Notice": SCREEN,
	"Munimji Purchase Proposal": SCREEN,
	"Munimji Agent Run": {M: "r", S: "r"},
	"Munimji Assistant Answer": {A: "rwcd", M: "rwcd", S: "r"},
	"Munimji Chat Log": {A: "c", M: "rc", S: "r"},
	"Munimji Vendor Message": {A: "rwc", M: "rwc", S: "r"},
	"Munimji Vendor Reply": {A: "rwc", M: "rwc", S: "r"},
	"Munimji Delivery Chase": SCREEN,
	"Munimji Receipt Check": SCREEN,
	"Munimji Quote Round": SCREEN,
	"Munimji Stock Transfer": SCREEN,
	"Munimji Cycle Count": {A: "rwc", M: "rwc", S: "r"},
	"Munimji Count Review": {A: "rwc", M: "rwc", S: "r"},
	"Munimji Lock": {A: "wc", M: "wc"},
}
EXPECTED: dict[str, dict[str, set[str]]] = {
	doctype: {role: set().union(*(RIGHTS[letter] for letter in letters)) for role, letters in roles.items()}
	for doctype, roles in EXPECTED_LETTERS.items()
}
CHILD_TABLES = {
	"Munimji Calendar Event"
}  # no permission rows of their own: a row is read and written with the page that holds it


def rights_and_defaults() -> dict[str, int]:
	"""Every right a permission row can grant on this site (the Check fields of DocPerm, including the custom `approve`) and what a row gives when the key is left out."""
	return {
		df.fieldname: int(df.default or 0)
		for df in frappe.get_meta("DocPerm").fields
		if df.fieldtype == "Check"
	}


def doctype_files() -> dict[str, dict]:
	found = {}
	for path in sorted(DOCTYPE_DIR.glob("*/*.json")):
		data = json.loads(path.read_text(encoding="utf-8"))
		if data.get("doctype") == "DocType":
			found[data["name"]] = data
	return found


def granted(row: dict) -> set[str]:
	defaults = rights_and_defaults()
	return {right for right, default in defaults.items() if int(row.get(right, default)) == 1}


class TestTheRightsOfEveryRole(IntegrationTestCase):
	def test_the_app_has_exactly_the_doctypes_this_test_knows(self):
		self.assertEqual(set(doctype_files()), set(EXPECTED) | CHILD_TABLES)
		self.assertEqual(
			set(frappe.get_all("DocType", filters={"module": MODULE}, pluck="name")),
			set(EXPECTED) | CHILD_TABLES,
		)
		for name in CHILD_TABLES:
			self.assertEqual(doctype_files()[name].get("istable"), 1, name)
			self.assertEqual(
				doctype_files()[name].get("permissions"),
				[],
				f"{name} is a child table: its rights are the page's",
			)

	def test_no_right_in_the_files_is_left_to_a_default(self):
		# Read as the standard sync reads it, a missing key is "off"; created through the ORM, or read by a later Frappe, it is the default, which is "on" for these.
		# So every right whose default is on is written out, 0 or 1.
		defaults = rights_and_defaults()
		left = []
		for doctype, data in doctype_files().items():
			for row in data["permissions"]:
				left += [
					f"{doctype} / {row['role']}: {right}"
					for right, default in defaults.items()
					if default == 1 and right not in row
				]
		self.assertEqual(
			left, [], "written out, these rights would not depend on how Frappe reads a missing key"
		)

	def test_the_files_grant_exactly_the_expected_rights_to_exactly_the_expected_roles(self):
		for doctype, expected in EXPECTED.items():
			rows = doctype_files()[doctype]["permissions"]
			self.assertEqual(
				sorted(r["role"] for r in rows), sorted(expected), f"{doctype}: the roles with a row"
			)
			for row in rows:
				self.assertEqual(granted(row), expected[row["role"]], f"{doctype} / {row['role']}: the file")

	def test_the_synced_rows_grant_exactly_the_same_rights(self):
		# what is in the database after install or migrate, which is what Frappe checks (the Role Permission Manager shows these)
		for doctype, expected in EXPECTED.items():
			rows = [r.as_dict() for r in frappe.get_meta(doctype).permissions]
			self.assertEqual(
				sorted(r["role"] for r in rows), sorted(expected), f"{doctype}: the roles with a row"
			)
			for row in rows:
				self.assertEqual(row["permlevel"], 0)
				self.assertEqual(
					{right for right in rights_and_defaults() if row.get(right)},
					expected[row["role"]],
					f"{doctype} / {row['role']}: the database",
				)
		self.assertEqual(
			frappe.get_all("Custom DocPerm", filters={"parent": ["in", list(EXPECTED)]}, pluck="name"),
			[],
			"no one has overridden the rows with the Role Permission Manager here",
		)

	def test_the_app_gives_a_munimji_role_no_right_on_anything_of_erpnext(self):
		ours = list(EXPECTED) + list(CHILD_TABLES)
		for table in ("DocPerm", "Custom DocPerm"):
			strangers = frappe.db.sql(
				f"SELECT parent, role FROM `tab{table}` WHERE role LIKE 'Munimji%%' AND parent NOT IN %(ours)s",
				{"ours": ours},
			)
			self.assertEqual(
				strangers, (), f"a Munimji role has rights on a DocType that is not this app's ({table})"
			)

	def test_the_three_roles_exist_and_no_other_role_carries_the_name(self):
		self.assertEqual(
			sorted(frappe.get_all("Role", filters={"name": ["like", "Munimji%"]}, pluck="name")),
			sorted(ROLES),
		)
		for role in ROLES:
			self.assertEqual(frappe.db.get_value("Role", role, ["disabled", "desk_access"]), (0, 1), role)

	def test_no_role_may_change_or_delete_a_row_of_the_audit_seal(self):
		for row in doctype_files()[SEAL]["permissions"]:
			self.assertFalse(granted(row) & {"write", "delete", "create", "import"}, row["role"])

	def test_no_doctype_of_the_stores_can_be_renamed_by_hand_or_tracks_changes_in_a_second_place(self):
		for doctype, data in doctype_files().items():
			if doctype in (SETTINGS,) or doctype in CHILD_TABLES:
				continue
			self.assertEqual(data.get("allow_rename"), 0, doctype)
			self.assertEqual(data.get("track_changes"), 0, doctype)


class TestWhatPeopleCanReallyDo(IntegrationTestCase):
	"""The same table seen from the other side: a person with one role, asked by Frappe itself, on every DocType of the app."""

	def setUp(self):
		self.viewer = make_user("munimji.viewer@example.com", ("Munimji Viewer",))
		self.approver = make_user("munimji.approver.only@example.com", ("Munimji Approver",))
		self.manager = make_user("munimji.manager@example.com", ("Munimji Manager",))
		self.sysmgr = make_user("munimji.sysmgr@example.com", ("System Manager",))
		self.stock_user = make_user(
			"munimji.stock@example.com", ("Stock User", "Purchase User", "Purchase Manager")
		)  # ERPNext's roles, none of ours
		self.nobody = make_user("munimji.nobody@example.com", ())
		self.roles = {
			self.viewer: {V},
			self.approver: {A},
			self.manager: {M},
			self.sysmgr: {S},
			self.stock_user: set(),
			self.nobody: set(),
		}

	def can(self, user: str, doctype: str, right: str) -> bool:
		return bool(frappe.has_permission(doctype, right, user=user))

	def test_every_person_gets_on_every_doctype_what_the_table_gives_their_role_and_nothing_else(self):
		every_right = {
			"read",
			"write",
			"create",
			"delete",
			"report",
			"export",
			"approve",
			"share",
			"print",
			"email",
		}
		for doctype, per_role in EXPECTED.items():
			for user, roles in self.roles.items():
				expected = set().union(*(per_role.get(role, set()) for role in roles))
				got = {right for right in every_right if self.can(user, doctype, right)}
				self.assertEqual(got, expected, f"{user} on {doctype}")

	def test_only_a_munimji_manager_and_a_system_manager_can_open_the_settings(self):
		for user, expected in (
			(self.manager, True),
			(self.sysmgr, True),
			(self.viewer, False),
			(self.approver, False),
			(self.stock_user, False),
			(self.nobody, False),
		):
			self.assertEqual(self.can(user, SETTINGS, "read"), expected, f"{user}: read")
			self.assertEqual(self.can(user, SETTINGS, "write"), expected, f"{user}: write")

	def test_nobody_but_those_two_can_get_the_settings_by_loading_the_document(self):
		for user in (self.viewer, self.approver, self.stock_user, self.nobody):
			with self.set_user(user), self.assertRaises(frappe.PermissionError):
				frappe.get_doc(SETTINGS).check_permission("read")
		with self.set_user(self.manager):
			frappe.get_doc(SETTINGS).check_permission("write")

	def test_nobody_can_share_print_or_email_a_record_of_the_app(self):
		for doctype in EXPECTED:
			for user in self.roles:
				for right in ("share", "print", "email"):
					self.assertFalse(self.can(user, doctype, right), f"{user}: {right} on {doctype}")

	def test_the_erpnext_roles_of_the_install_notes_are_what_let_a_person_see_stock_and_make_orders(self):
		# docs/INSTALL.md says: Stock User to see stock, Purchase User and Purchase Manager to make a Purchase Order. Asked of ERPNext, here.
		stock_only = make_user("munimji.stock.only@example.com", ("Stock User",))
		purchase_user = make_user("munimji.purchase.user@example.com", ("Purchase User",))
		for doctype in ("Item", "Bin", "Stock Ledger Entry", "Warehouse"):
			self.assertTrue(self.can(stock_only, doctype, "read"), f"Stock User reads {doctype}")
		self.assertFalse(
			self.can(purchase_user, "Stock Ledger Entry", "read"),
			"Purchase User does not read the stock ledger: that is what Stock User is for",
		)
		self.assertFalse(
			self.can(stock_only, "Purchase Order", "create"), "Stock User alone cannot make an order"
		)
		self.assertTrue(
			self.can(purchase_user, "Purchase Order", "create"),
			"measured on ERPNext 16.53.0: Purchase User alone may create a Purchase Order",
		)
		self.assertTrue(
			self.can(self.stock_user, "Purchase Order", "create"),
			"Stock User + Purchase User + Purchase Manager can",
		)

	def test_the_munimji_roles_give_no_access_to_what_erpnext_holds(self):
		for doctype in ("Item", "Bin", "Stock Ledger Entry", "Purchase Order", "Supplier"):
			for user in (self.viewer, self.approver, self.manager):
				self.assertFalse(
					self.can(user, doctype, "read"), f"{user} reads {doctype} with a Munimji role alone"
				)
