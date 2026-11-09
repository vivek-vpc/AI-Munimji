"""An item the engine cannot analyse is skipped so that the others are looked at; the run says how many, and the Settings page shows it after the run.

What the job does with a real item that fails is in test_jobs.py. Here: the sentence and its reader, the engine's own words they depend on, and the page's JavaScript run under Node with every
combination of the notes at the top of the page (the intro is one slot: no note may wipe another).
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import frappe

from ai_munimji import last_run

SETTINGS_JS = Path(
	frappe.get_app_path(
		"ai_munimji", "ai_munimji", "doctype", "ai_munimji_settings", "ai_munimji_settings.js"
	)
)

HARNESS = """
const fs = require("fs");
let handlers = {};
global.frappe = {
	ui: { form: { on: (doctype, h) => { handlers = h; } } },
	utils: { escape_html: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;") },
};
global.__ = (s, args) => (args ? s.replace(/\\{(\\d+)\\}/g, (_, i) => args[i]) : s);
eval(fs.readFileSync(process.argv[2], "utf8"));
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map((c) => {
	let intro = null;
	const frm = { doc: { enabled: c.enabled, __onload: c.onload }, set_intro: (text, color) => { intro = [text, color]; } };
	handlers.refresh(frm);
	return intro;
})));
"""

WARNING = "MariaDB has innodb_snapshot_isolation ON."
OFF = "Stock monitoring is off."


class TestTheSentence(unittest.TestCase):
	def test_it_says_how_many_and_is_read_back(self):
		self.assertIsNone(last_run.note(0))
		self.assertEqual(last_run.note(1), "1 item could not be analysed")
		self.assertEqual(last_run.note(3), "3 items could not be analysed")
		for count in (1, 2, 3, 40, 5000):
			self.assertEqual(last_run.count_in(last_run.note(count)), count)

	def test_anything_else_in_the_record_counts_as_nothing(self):
		for text in (
			None,
			"",
			"RuntimeError: the ERP is down",
			"0 items could not be analysed later",
			"x 3 items could not be analysed",
		):
			self.assertEqual(last_run.count_in(text), 0, text)

	def test_the_items_are_found_in_the_engines_errors_once_each(self):
		errors = [
			"BOLT-M8: analysis failed (division by zero)",
			"NUT-M8: no stock data returned by the ERP",  # skipped too, but not an analysis that failed: not counted
			"BOLT-M8: analysis failed (again)",
			"WASHER: analysis failed (boom)",
			"PIPE: a reconcile problem",
			"Item: with a colon: analysis failed (x)",
		]
		self.assertEqual(last_run.unanalysed_items(errors), ["BOLT-M8", "Item: with a colon", "WASHER"])
		self.assertEqual(last_run.unanalysed_items([]), [])

	def test_the_engines_words_are_the_ones_read(self):
		"""If the engine changes how it reports an item it could not analyse, this fails here, not silently on the page."""
		import inspect

		from ai_munimji_engine.packs.stock_procurement.inventory import agent

		self.assertIn('f"{it.code}: analysis failed ({exc})"', inspect.getsource(agent.InventoryAgent.run))
		self.assertTrue(last_run.ANALYSIS_FAILED.match("X-1: analysis failed (boom)"))


@unittest.skipUnless(shutil.which("node"), "Node is needed to run the page's script")
class TestTheNotesAtTheTopOfThePage(unittest.TestCase):
	def intros(self, *cases):
		with tempfile.TemporaryDirectory() as folder:
			harness = Path(folder) / "harness.js"
			harness.write_text(HARNESS, encoding="utf-8")
			out = subprocess.run(
				["node", str(harness), str(SETTINGS_JS), json.dumps(list(cases))],
				capture_output=True,
				text=True,
				check=True,
				timeout=60,
			).stdout
		return json.loads(out)

	def test_every_note_is_there_together_and_none_wipes_another(self):
		[plain, off, skipped_one, skipped_three, everything] = self.intros(
			{"enabled": 1, "onload": {}},
			{"enabled": 0, "onload": {}},
			{"enabled": 1, "onload": {"unanalysed_items": 1}},
			{"enabled": 1, "onload": {"unanalysed_items": 3}},
			{"enabled": 0, "onload": {"snapshot_isolation_warning": WARNING, "unanalysed_items": 3}},
		)
		self.assertEqual(plain, ["", "yellow"], "nothing to say, nothing said")
		self.assertEqual(off, [OFF + " Review the thresholds below, then switch on Watch stock.", "yellow"])
		self.assertEqual(
			skipped_one[0],
			"1 item could not be analysed in the last stock check and was skipped. Open the latest Munimji Agent Run to see which.",
		)
		self.assertTrue(
			skipped_three[0].startswith(
				"3 items could not be analysed in the last stock check and were skipped."
			)
		)
		text = everything[0]
		for part in (WARNING, OFF, "3 items could not be analysed"):
			self.assertIn(part, text)
		self.assertLess(text.index(WARNING), text.index(OFF), "the database warning stays first")
		self.assertLess(text.index(OFF), text.index("3 items could not be analysed"))
		self.assertEqual(everything[1], "red", "the warning keeps the page red")
		self.assertEqual(skipped_three[1], "yellow")
