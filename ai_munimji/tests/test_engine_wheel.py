import importlib
import importlib.metadata
import json
import pkgutil
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = "ai-munimji-engine"


def declared_engine_requirements() -> list[Requirement]:
	dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
		"dependencies"
	]
	return [r for r in (Requirement(line) for line in dependencies) if r.name == DISTRIBUTION]


class TestTheEngineInTheBench(unittest.TestCase):
	"""The engine is not on PyPI, so dev/install-engine.sh puts a local wheel into the bench's environment. These tests say that it really is the wheel, that it is what the app
	declares, and that it runs here, in Frappe's own environment (Python 3.14 with Frappe's pinned pydantic and PyYAML)."""

	def test_the_app_declares_the_engine_on_one_line(self):
		declared = declared_engine_requirements()
		self.assertEqual(
			len(declared),
			1,
			"one dependency line for the engine, so that changing how it arrives is a change of one line",
		)
		self.assertTrue(declared[0].specifier, "the line names the versions this app was run against")
		self.assertIsNone(
			declared[0].url, "a plain name: a path or URL on this line would only work on one machine"
		)

	def test_what_is_installed_satisfies_that_line(self):
		declared = declared_engine_requirements()[0]
		installed = importlib.metadata.version(DISTRIBUTION)
		self.assertIn(
			installed,
			declared.specifier,
			f"{DISTRIBUTION} {installed} is installed; the app asks for {declared.specifier}",
		)

	def test_it_is_the_installed_wheel_and_not_a_checkout_on_the_path(self):
		import ai_munimji_engine

		file = Path(ai_munimji_engine.__file__).resolve()
		self.assertIn("site-packages", file.parts, f"imported from {file}")
		direct_url = importlib.metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
		if direct_url:  # present when it came from a local file; an editable install would say so
			self.assertFalse(
				json.loads(direct_url).get("dir_info", {}).get("editable"),
				"the engine is an editable checkout, not the wheel",
			)

	def test_the_engine_brings_only_what_frappe_already_has(self):
		requires = importlib.metadata.requires(DISTRIBUTION) or []
		names = {Requirement(r).name.lower() for r in requires if "extra ==" not in r}
		self.assertEqual(
			names, {"pydantic", "pyyaml"}, "a third dependency would be installed into every customer's bench"
		)

	def test_every_module_of_the_engine_imports_here(self):
		import ai_munimji_engine

		names = sorted(
			m.name
			for m in pkgutil.walk_packages(ai_munimji_engine.__path__, prefix="ai_munimji_engine.")
			if not m.name.endswith(".__main__")
		)
		self.assertGreater(len(names), 40, "the engine is about 70 modules; fewer means an incomplete wheel")
		failed = {}
		for name in names:
			try:
				importlib.import_module(name)
			except Exception as exc:
				failed[name] = f"{type(exc).__name__}: {exc}"
		self.assertEqual(failed, {})

	def test_the_rules_run_in_the_bench(self):
		from ai_munimji_engine.packs.stock_procurement.erp import DailyUsage, ItemInfo, StockInfo
		from ai_munimji_engine.packs.stock_procurement.inventory.analysis import analyze_item
		from ai_munimji_engine.packs.stock_procurement.settings import Policy

		today = date(2026, 11, 6)
		usage = [DailyUsage(today - timedelta(days=n), 1.0) for n in range(1, 31)]
		low = analyze_item(
			ItemInfo(code="X", name="X"), StockInfo(on_hand=3), usage, Policy(min_days_cover=7), today
		)
		plenty = analyze_item(
			ItemInfo(code="X", name="X"), StockInfo(on_hand=300), usage, Policy(min_days_cover=7), today
		)
		self.assertNotEqual(low.kind, "OK", "3 on hand at 1 a day is not enough cover")
		self.assertEqual(plenty.kind, "OK")
		self.assertLess(low.cover_days_on_hand, plenty.cover_days_on_hand)
