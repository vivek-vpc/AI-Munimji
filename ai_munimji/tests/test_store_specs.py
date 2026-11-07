"""The DocType files and the table in docs/STORES.md are what ai_munimji/stores/specs.py says, and the specs describe the engine's stores completely.

The files are written from the specs by dev/scripts/make_doctypes.py; a hand edit of a DocType file, or a change of the specs that was not followed by the script, fails here.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from ai_munimji.stores.specs import BY_DOCTYPE, TABLES

ROOT = Path(__file__).resolve().parents[2]
HAND_WRITTEN = {"Munimji Approval Request", "Munimji Audit Seal"}  # controllers with more than the base class


class TestTheFilesAreMadeFromTheSpecs(unittest.TestCase):
	def test_the_generator_would_change_nothing(self):
		done = subprocess.run(
			[sys.executable, str(ROOT / "dev" / "scripts" / "make_doctypes.py"), "--check"],
			capture_output=True,
			text=True,
			check=False,
		)
		self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

	def test_there_are_25_doctypes_and_each_names_one_table_of_the_engine(self):
		self.assertEqual(len(TABLES), 25)
		self.assertEqual(len({t.doctype for t in TABLES}), 25)
		self.assertEqual(len({t.engine for t in TABLES}), 25)

	def test_every_store_table_of_the_engine_has_a_doctype(self):
		from ai_munimji_engine.stores import memory_core_stores
		from ai_munimji_engine.stores.stock import memory_stock_stores

		core = memory_core_stores()
		memory_stock_stores(core.backend)
		# the tables the memory fakes use are the tables the engine's Protocols describe (their docstrings name them); the lock table is the app's own
		used = set()
		for store in (
			core.approvals,
			core.audit,
			core.settings,
			core.workorders,
			core.agents,
			core.jobs,
			core.inbound,
		):
			used |= _tables_named_in(type(store).__module__)
		from ai_munimji_engine.stores import stock as stock_package

		for module in (
			"alerts",
			"assistant",
			"followup",
			"movements",
			"notices",
			"proposals",
			"runs",
			"vendors",
		):
			used |= _tables_named_in(f"{stock_package.__name__}.{module}")
		self.assertGreaterEqual(
			len(used),
			20,
			"the scan sees the tables the stores use, so that it cannot pass by looking at nothing",
		)
		missing = used - {t.engine for t in TABLES}
		self.assertEqual(missing, set(), "a table of the engine's stores has no DocType")

	def test_the_record_classes_are_store_records_except_the_two_written_by_hand_which_are_too(self):
		from ai_munimji.stores.record import StoreRecord

		for table in TABLES:
			module = (
				"ai_munimji.ai_munimji.doctype."
				+ table.doctype.lower().replace(" ", "_")
				+ "."
				+ table.doctype.lower().replace(" ", "_")
			)
			cls = getattr(
				__import__(module, fromlist=["x"]), "".join(w.capitalize() for w in table.doctype.split())
			)
			self.assertTrue(issubclass(cls, StoreRecord), table.doctype)

	def test_no_doctype_grants_anyone_a_right_the_table_of_docs_does_not_show(self):
		text = (ROOT / "docs" / "STORES.md").read_text(encoding="utf-8")
		for table in TABLES:
			self.assertIn(f"| {table.doctype} |", text)
		self.assertIs(BY_DOCTYPE["Munimji Audit Seal"].numbered, True)


def _tables_named_in(module_name: str) -> set[str]:
	import importlib
	import re

	source = Path(importlib.import_module(module_name).__file__).read_text(encoding="utf-8")
	return set(re.findall(r'db\.(?:rows|insert)\("(\w+)"', source))
