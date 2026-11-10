import re
import unittest
from pathlib import Path

from ai_munimji.install import ROLES

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


class TestTheInstallNotes(unittest.TestCase):
	def setUp(self):
		self.text = (DOCS / "INSTALL.md").read_text(encoding="utf-8")

	def test_they_name_the_munimji_roles_and_the_erpnext_roles_a_person_needs(self):
		for role in (*ROLES, "Stock User", "Purchase User"):
			self.assertIn(role, self.text, f"docs/INSTALL.md does not name {role}")

	def test_they_say_what_was_measured_about_purchase_user(self):
		self.assertIn("Purchase User is enough to create a Purchase Order", self.text)
		self.assertIn("ERPNext 16.53.0 and again on 16.54.0", self.text)
		self.assertIn(
			"service account",
			self.text,
			"the standalone service's wider list of roles is said to be a service-account matter",
		)

	def test_they_say_the_monitor_starts_off(self):
		self.assertIn("the stock monitor is off", self.text)

	def test_they_say_the_app_adds_no_permission_rows_to_erpnext(self):
		self.assertIn("no permission rows to any ERPNext DocType", self.text)

	def test_they_say_what_a_purchase_user_alone_can_and_cannot_do_with_an_order(self):
		self.assertIn(
			"also enough to change the quantity of an order made from a request and to cancel it", self.text
		)
		self.assertIn(
			"Purchase Manager adds nothing",
			self.text,
			"Purchase Manager is named only to say that it is not needed (measured in tests/world/test_order_changes.py)",
		)

	def test_they_say_how_taxes_behave_when_a_person_cannot_read_tax_rules(self):
		for sentence in (
			"Tax Rules needs the Accounts Manager role",
			"keeps the figures it used with the request",
			"not from a fresh read as that person",
			"Taxes are not included in these totals",
			"A tax of zero is never shown as if it were a result",
			"Duties and taxes are not in this comparison",
		):
			self.assertIn(sentence, self.text)

	def test_what_they_say_the_request_shows_is_what_the_engine_shows(self):
		# the two sentences a person reads in a request are the engine's own; if the engine changes them, these notes are wrong until they are changed too
		from ai_munimji_engine.packs.stock_procurement.procurement import scoring

		source = Path(scoring.__file__).read_text(encoding="utf-8")
		self.assertIn("Taxes are not included in these totals", source)
		self.assertIn("Duties and taxes are not in this comparison", source)

	def test_they_name_the_version_they_describe(self):
		from ai_munimji import __version__

		self.assertIn(f"version **{__version__}**", self.text)

	def test_they_say_which_versions_it_was_run_on(self):
		self.assertIn("Frappe 16.55.2 and ERPNext 16.54.0", self.text)


PUBLIC_TEXT = (
	"README.md",
	"pyproject.toml",
	"dev/README.md",
	"ai_munimji/hooks.py",
	*sorted(f"docs/{p.name}" for p in DOCS.glob("*.md")),
)
# what the project does not say about itself, and the claims it cannot make yet: no listing, no release, no version it was not run on
FORBIDDEN = {
	r"small business": "a size of customer is not a claim the project makes",
	r"working prototype": "it is in development; it is not a prototype that works",
	r"(?<!not )(?<!not on )(?<!not in )(?<!not listed on )(?:available|listed|published|found) (?:on|in) the (?:frappe )?marketplace": "it is not on the Marketplace",
	r"(?<!not )(?<!not yet )(?:is|are) (?:now )?released": "it is not released",
	r"production[- ]ready": "it is not",
	r"(?:compatible|works|tested|runs) (?:with|on) (?:frappe|erpnext)\s*v?(?:1[0-5]|1[7-9]|[2-9]\d)\b": "only version 16 was run",
}


# A path of the owner's machine, a Windows user folder or another of their projects must not be in a file that will be public. The files are READ here, one by one: `git grep` with a Windows
# path in it missed one (dev/README.md, phase 6), so no check of this kind may rely on it.
PERSONAL = (
	"C:\\ERP",
	"C:/ERP",
	"\\Users\\",
	"/Users/",
	"AppData",
	"OneDrive",
	"registry-prep",
	"listing-drafts",
	"Automotive chatbot",
)
TEXT_SUFFIXES = {
	".md",
	".py",
	".sh",
	".ps1",
	".yml",
	".yaml",
	".json",
	".js",
	".cjs",
	".toml",
	".txt",
	".cfg",
	".html",
	".pot",
}
SKIPPED_FOLDERS = {".git", "node_modules", "__pycache__", "wheels", ".cache", "locale"}
GENERATED = ("dev/contract-",)  # made by the loader on a development machine, never committed (.gitignore)


class TestNoPersonalPaths(unittest.TestCase):
	def test_no_file_of_the_repository_names_a_path_or_a_project_of_the_owners_machine(self):
		import os

		found, read = [], 0
		for folder, subfolders, names in os.walk(ROOT):
			subfolders[:] = sorted(
				s for s in subfolders if s not in SKIPPED_FOLDERS
			)  # not descended into at all: node_modules is big
			for name in sorted(names):
				path = Path(folder) / name
				relative = path.relative_to(ROOT).as_posix()
				if (
					path.suffix not in TEXT_SUFFIXES
					or relative.startswith(GENERATED)
					or relative == "ai_munimji/tests/test_docs.py"  # this file names them
				):
					continue
				text = path.read_text(encoding="utf-8", errors="replace")
				read += 1
				found += [f"{relative}: {needle!r}" for needle in PERSONAL if needle in text]
		self.assertGreater(read, 100, "the test reads the repository's text files")
		self.assertEqual(found, [])


RELEASE_WORDING = (
	"README.md",
	"pyproject.toml",
	"ai_munimji/hooks.py",
	"docs/INSTALL.md",
	"docs/KNOWN_LIMITATIONS.md",
	"dev/new-app.sh",
)
STALE = (
	r"not released",
	r"in development",
	r"early stage",
	r"not on the (?:frappe )?marketplace",
	r"early spike",
)


class TestTheReleaseWording(unittest.TestCase):
	"""Version 0.1.1 is the version that is released. The files that describe the app to a person no longer say that it is in development or not released (the release commit,
	docs/RELEASE_CHECKLIST.md), and the version is the same everywhere it is written."""

	def test_no_file_that_describes_the_app_says_it_is_in_development_or_not_released(self):
		found = []
		for relative in RELEASE_WORDING:
			text = (ROOT / relative).read_text(encoding="utf-8")
			for pattern in STALE:
				found += [f"{relative}: “{m.group(0)}”" for m in re.finditer(pattern, text, re.I)]
		self.assertEqual(found, [])
		self.assertTrue(all((ROOT / relative).exists() for relative in RELEASE_WORDING))

	def test_the_version_is_the_same_everywhere_and_the_engine_is_pinned_to_the_one_installed(self):
		from importlib.metadata import version

		from ai_munimji import __version__

		self.assertEqual(__version__, "0.1.1")
		self.assertIn(f"## {__version__} (", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
		pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
		self.assertIn(
			f'"ai-munimji-engine=={version("ai-munimji-engine")}"',
			pyproject,
			"an exact pin, the engine this bench has",
		)
		self.assertEqual(
			re.search(r'(?m)^description = "(.*)"', pyproject).group(1),
			re.search(
				r'(?m)^app_description = "(.*)"', (ROOT / "ai_munimji/hooks.py").read_text(encoding="utf-8")
			).group(1),
			"one description for pyproject.toml and hooks.py",
		)

	def test_every_page_that_names_the_version_of_the_app_names_this_one(self):
		"""The pages that say which version they describe (README, the install notes, the limitations, the release checklist, the registry file in the listing) say the version of
		`ai_munimji/__init__.py`. The changelog is history and names every version."""
		from ai_munimji import __version__

		named = 0
		for relative in (
			"README.md",
			"docs/INSTALL.md",
			"docs/KNOWN_LIMITATIONS.md",
			"docs/RELEASE_CHECKLIST.md",
			"docs/LISTING.md",
		):
			text = (ROOT / relative).read_text(encoding="utf-8")
			found = re.findall(r'[Vv]ersion \*{0,2}(\d+\.\d+\.\d+)|"version": "(\d+\.\d+\.\d+)"', text)
			versions = {a or b for a, b in found}
			named += len(found)
			self.assertEqual(
				versions - {__version__}, set(), f"{relative} names a version that is not {__version__}"
			)
		self.assertGreaterEqual(named, 5, "the scan sees the places that name the version")


class TestWhatThePublicTextSaysAboutTheApp(unittest.TestCase):
	def test_no_public_text_says_what_the_project_does_not_say_or_cannot_claim(self):
		found = []
		for relative in PUBLIC_TEXT:
			text = (ROOT / relative).read_text(encoding="utf-8")
			for pattern, why in FORBIDDEN.items():
				for match in re.finditer(pattern, text, re.I):
					found.append(f"{relative}: “{match.group(0)}” ({why})")
		self.assertEqual(found, [])

	def test_the_scan_sees_the_files_it_is_meant_to_see(self):
		self.assertGreaterEqual(len(PUBLIC_TEXT), 7)
		for needed in ("README.md", "docs/INSTALL.md", "docs/UNINSTALL.md", "docs/NAMES.md"):
			self.assertIn(needed, PUBLIC_TEXT)

	def test_the_patterns_do_catch_what_they_are_for(self):
		for text in (
			"A tool for a small business",
			"a working prototype",
			"It is available on the Marketplace",
			"AI Munimji is released",
			"production-ready",
			"Works with ERPNext 15",
			"compatible with Frappe 17",
		):
			self.assertTrue(any(re.search(p, text, re.I) for p in FORBIDDEN), text)
		for text in (
			"It is not released",
			"not listed on the Frappe Marketplace",
			"It has been run only on Frappe 16.55.2 and ERPNext 16.54.0",
			"not available on the Marketplace",
		):
			self.assertFalse(any(re.search(p, text, re.I) for p in FORBIDDEN), text)
