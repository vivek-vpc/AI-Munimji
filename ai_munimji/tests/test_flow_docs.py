"""The words about how a request flows are the same on the Settings page, in the user guide and in the listing text, and the two documents are plain UTF-8 (Group 2, F5 of the production-readiness
review).

Word saved some of the documents as UTF-16, which Git shows as a binary file and a text search cannot read; these two are checked for it. The sentences are compared after the differences of
their setting are taken away (curly or straight quotes, bold marks), so a change to one of the three that is not made in the others fails here.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SETTINGS = ROOT / "ai_munimji" / "ai_munimji" / "doctype" / "ai_munimji_settings"

SENTENCES = (
	"The stock check looks at every item. For each one that is running low it makes a Reorder request and tells the people who may approve.",
	"When an approver approves a reorder, the vendors are compared in the background (price, delivery time, how often each delivered on time). About a minute later a Purchase request appears in Munimji Approval Request, with the vendor it recommends and why it did not choose the others.",
	"For an item with no purchase history no comparison is possible: the request says so, and you order it in ERPNext by hand and press Got it.",
	"When an approver approves the purchase request, ERPNext gets a Draft Purchase Order in the approver's name. It is only a draft: open it in ERPNext, check it and submit it. Nothing is sent to the vendor.",
	"The vendor comparison starts right after a reorder is approved and takes about a minute; if a stock check is running at that moment, the next scheduled check makes it.",
	"Viewers see the requests. Approvers also answer them and make the draft order. Managers also change the settings and run the check.",
)


def plain(text: str) -> str:
	"""The text without what its setting adds: Markdown bold, curly quotes, straight double quotes (a JavaScript string's own), and the spaces."""
	for curly, straight in (
		(0x201C, '"'),
		(0x201D, '"'),
		(0x2018, "'"),
		(0x2019, "'"),
	):  # the curly quotes of Word and of the page
		text = text.replace(chr(curly), straight)
	text = text.replace("**", "").replace("\\", "").replace('"', "")
	return re.sub(r"\s+", " ", text)


class TestHowARequestFlows(unittest.TestCase):
	def test_the_user_guide_and_the_listing_are_utf8_without_a_byte_order_mark(self):
		for name in ("USER_GUIDE.md", "LISTING.md"):
			data = (DOCS / name).read_bytes()
			self.assertNotEqual(data[:3], b"\xef\xbb\xbf", f"{name} starts with a byte-order mark")
			self.assertNotIn(data[:2], (b"\xff\xfe", b"\xfe\xff"), f"{name} is UTF-16 (saved by Word?)")
			self.assertNotIn(b"\x00", data, f"{name} holds NUL bytes: it is not UTF-8 text")
			self.assertNotIn(b"\r", data, f"{name} has Windows line endings: the repository keeps LF")
			data.decode("utf-8")

	def test_the_three_places_say_the_same_things(self):
		places = {
			"docs/USER_GUIDE.md": (DOCS / "USER_GUIDE.md").read_text(encoding="utf-8"),
			"docs/LISTING.md": (DOCS / "LISTING.md").read_text(encoding="utf-8"),
			"the Settings page": (SETTINGS / "ai_munimji_settings.js").read_text(encoding="utf-8"),
		}
		for where, text in places.items():
			for sentence in SENTENCES:
				self.assertIn(plain(sentence), plain(text), f"{where} does not say: {sentence}")

	def test_the_guide_and_the_listing_have_a_section_called_how_a_request_flows(self):
		self.assertIn("\n## How a request flows\n", (DOCS / "USER_GUIDE.md").read_text(encoding="utf-8"))
		self.assertIn("**How a request flows**", (DOCS / "LISTING.md").read_text(encoding="utf-8"))

	def test_nothing_still_says_the_vendors_wait_for_the_next_scheduled_run(self):
		for name in ("USER_GUIDE.md", "LISTING.md"):
			text = (DOCS / name).read_text(encoding="utf-8")
			for stale in (
				"At the next run of the scheduled job",
				"the next run compares",
				"At its next run, the app compares",
			):
				self.assertNotIn(stale, text, f"{name} still says: {stale}")

	def test_the_settings_page_has_the_status_block_the_button_and_the_section(self):
		page = json.loads((SETTINGS / "ai_munimji_settings.json").read_text(encoding="utf-8"))
		order = page["field_order"]
		for field in ("check_section", "check_status", "run_check_now", "flow_section", "flow_help"):
			self.assertIn(field, order)
		by_name = {f["fieldname"]: f for f in page["fields"]}
		self.assertEqual(by_name["run_check_now"]["fieldtype"], "Button")
		self.assertEqual(by_name["run_check_now"]["label"], "Run the check now")
		self.assertEqual(by_name["flow_section"]["label"], "How a request flows")
		self.assertLess(
			order.index("enabled"), order.index("check_section"), "after Watch stock, before the rules"
		)
		self.assertLess(order.index("flow_help"), order.index("rules_section"))
