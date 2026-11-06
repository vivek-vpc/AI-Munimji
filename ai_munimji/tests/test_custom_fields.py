import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from ai_munimji import custom_fields, hooks
from ai_munimji.uninstall import CUSTOM_FIELDS

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "custom_field.json"

# A COPY of what the standalone service creates with `erp-agents erp-setup`: erpnext-ai-agents, src/erp_agents/core/erp/erpnext.py, ERPNextClient.CUSTOM_FIELDS, as of
# commit 7f9bb9d (6 Nov 2026). (fieldname, fieldtype, insert_after, search_index); every one is read-only, not copied and hidden in print. If the service changes its fields, this
# copy, ai_munimji/custom_fields.py, the fixture and docs/NAMES.md change together, or an order made by one product is no longer recognised by the other.
STANDALONE = {
	"Purchase Order": (
		("custom_agent_ref", "Data", "supplier_name", 1),
		("custom_agent_approved_by", "Data", "custom_agent_ref", 0),
	),
	"Material Request": (
		("custom_agent_ref", "Data", "company", 1),
		("custom_agent_approved_by", "Data", "custom_agent_ref", 0),
		("custom_agent_note", "Small Text", "custom_agent_approved_by", 0),
	),
	"Stock Entry": (
		("custom_agent_ref", "Data", "company", 1),
		("custom_agent_approved_by", "Data", "custom_agent_ref", 0),
	),
}


class TestTheFieldsAreTheStandalonesFields(IntegrationTestCase):
	def test_same_names_types_positions_and_flags_as_erp_setup_makes(self):
		ours = {
			(f.dt, f.fieldname, f.fieldtype, f.insert_after, f.search_index) for f in custom_fields.FIELDS
		}
		theirs = {(dt, *row) for dt, rows in STANDALONE.items() for row in rows}
		self.assertEqual(ours, theirs)
		self.assertEqual(custom_fields.FLAGS, {"read_only": 1, "no_copy": 1, "print_hide": 1})
		self.assertEqual(len(custom_fields.NAMES), 7)

	def test_the_fixture_file_holds_exactly_these_seven_and_nothing_else(self):
		records = json.loads(FIXTURE.read_text(encoding="utf-8"))
		self.assertEqual(sorted(r["name"] for r in records), sorted(custom_fields.NAMES))
		by_name = {r["name"]: r for r in records}
		for f in custom_fields.FIELDS:
			record = by_name[f.name]
			self.assertEqual(
				(
					record["doctype"],
					record["dt"],
					record["fieldname"],
					record["fieldtype"],
					record["insert_after"],
					record["search_index"],
				),
				("Custom Field", f.dt, f.fieldname, f.fieldtype, f.insert_after, f.search_index),
				f.name,
			)
			self.assertEqual(record["label"], f.label)
			self.assertEqual(record["description"], f.description)
			for flag, value in custom_fields.FLAGS.items():
				self.assertEqual(record[flag], value, f"{f.name}: {flag}")
			self.assertEqual(
				record["unique"],
				0,
				f"{f.name}: the reference is not unique (a cancelled order and its replacement share one)",
			)
			self.assertFalse(
				record.get("module"), f"{f.name}: a module would make Frappe export it with the DocType"
			)

	def test_hooks_export_only_these_and_the_uninstall_removes_only_these(self):
		self.assertEqual(
			hooks.fixtures, [{"dt": "Custom Field", "filters": [["name", "in", list(custom_fields.NAMES)]]}]
		)
		self.assertEqual(tuple(CUSTOM_FIELDS), custom_fields.NAMES)

	def test_the_install_made_them_with_the_right_settings(self):
		for f in custom_fields.FIELDS:
			self.assertTrue(frappe.db.exists("Custom Field", f.name), f.name)
			field = frappe.get_meta(f.dt).get_field(f.fieldname)
			self.assertEqual(
				(
					field.fieldtype,
					field.read_only,
					field.no_copy,
					field.print_hide,
					field.search_index,
					field.unique,
				),
				(f.fieldtype, 1, 1, 1, f.search_index, 0),
				f.name,
			)
			self.assertTrue(frappe.db.has_column(f.dt, f.fieldname), f"{f.dt} has no column {f.fieldname}")

	def test_the_reference_has_an_index_and_it_does_not_forbid_a_second_row(self):
		for dt in custom_fields.DOCTYPES:
			indexes = frappe.db.sql(
				f"SHOW INDEX FROM `tab{dt}` WHERE Column_name = 'custom_agent_ref'", as_dict=True
			)
			self.assertTrue(indexes, f"{dt}: no index on custom_agent_ref")
			self.assertEqual({i["Non_unique"] for i in indexes}, {1}, f"{dt}: the index is unique")

	def test_no_other_field_of_the_standalone_kind_was_added(self):
		found = frappe.get_all("Custom Field", filters={"fieldname": ["like", "custom_agent%"]}, pluck="name")
		self.assertEqual(sorted(found), sorted(custom_fields.NAMES))
