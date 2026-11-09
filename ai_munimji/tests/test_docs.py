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

	def test_they_do_not_claim_a_release(self):
		self.assertIn("not released", self.text)
		self.assertIn("not on the Frappe Marketplace", self.text)

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


# Named exceptions: a phrase that the patterns above would catch but that says nothing about this app. Each is a decision, with the reason, and test_the_exceptions_are_still_in_the_text
# fails if the phrase goes away, so that an exception cannot outlive its reason.
ALLOWED_PHRASES = {
	"docs/PRIVACY.md": (
		"before that version is released",  # about a LATER version ("this policy will be updated before that version is released"), not a claim that this one is
	),
}


class TestWhatThePublicTextSaysAboutTheApp(unittest.TestCase):
	def test_the_exceptions_are_still_in_the_text_and_do_not_hide_a_real_claim(self):
		for relative, phrases in ALLOWED_PHRASES.items():
			text = (ROOT / relative).read_text(encoding="utf-8")
			for phrase in phrases:
				self.assertIn(
					phrase,
					text,
					f"{relative} no longer holds the exception {phrase!r}: remove it from ALLOWED_PHRASES",
				)
		released = r"(?<!not )(?<!not yet )(?:is|are) (?:now )?released"
		self.assertIn(released, FORBIDDEN)
		self.assertTrue(
			re.search(released, "AI Munimji is released", re.I), "the pattern still catches a real claim"
		)

	def test_no_public_text_says_what_the_project_does_not_say_or_cannot_claim(self):
		found = []
		for relative in PUBLIC_TEXT:
			text = (ROOT / relative).read_text(encoding="utf-8")
			for phrase in ALLOWED_PHRASES.get(relative, ()):
				text = text.replace(phrase, "")
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
