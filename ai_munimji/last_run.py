"""What the last stock check could not do, said once where a person looks: at the top of the AI Munimji Settings page.

The engine skips an item it cannot analyse and goes on with the others (one bad item must not stop the run); it records the fact only in the run's list of errors. The scheduled job
(jobs.py) counts those items, keeps the count as one short sentence in the `last_error` of the stock check's Job Run record ("3 items could not be analysed"; the run itself went well),
and the Settings page reads it back here. A later run that analyses every item writes nothing there, and the note goes. No module of the engine is imported here.
"""

import re

import frappe

STOCK_CHECK = "stock_check"  # the Job Run record of the stock check
# the engine's own words for an item it could not analyse (inventory/agent.py: f"{item_code}: analysis failed ({error})"); tests/test_skipped_items.py pins them against the engine
ANALYSIS_FAILED = re.compile(r"^(?P<item>.+?): analysis failed \(")
NOTE = re.compile(r"^(?P<count>\d+) items? could not be analysed$")


def unanalysed_items(errors: list[str]) -> list[str]:
	"""The item codes the engine could not analyse in a run, from the run's errors, once each."""
	return sorted({m["item"] for e in errors if (m := ANALYSIS_FAILED.match(e))})


def note(count: int) -> str | None:
	"""The sentence kept with the run, or None when every item was analysed."""
	if count <= 0:
		return None
	return "1 item could not be analysed" if count == 1 else f"{count} items could not be analysed"


def count_in(text: str | None) -> int:
	"""The count in a sentence made by `note`; 0 for anything else (no note, or the message of a run that failed)."""
	m = NOTE.match(text or "")
	return int(m["count"]) if m else 0


def unanalysed_in_last_check() -> int:
	"""How many items the last stock check could not analyse, read as the signed-in person: 0 when none, when it never ran, when it failed, or when this person may not read the record."""
	from ai_munimji.stores import (
		frappe_core_stores,  # here: the page must still load where the engine is not installed
	)

	try:
		row = frappe_core_stores().jobs.get(STOCK_CHECK)
	except frappe.PermissionError:
		return 0
	if not row or not row.get("last_ok"):
		return 0
	return count_in(row.get("last_error"))
