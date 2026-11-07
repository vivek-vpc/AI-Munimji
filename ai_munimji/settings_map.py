"""AI Munimji Settings and the engine's settings models: the one table that says which field of the page is which setting of the engine, and the validation that follows from it.

The rules are the engine's, not this app's: a value is accepted on the settings page exactly when the standalone service accepts it in `settings.yaml`, because the same pydantic models
(Policy, StockSystemSettings, CalendarSettings) decide in both. Field names on the page are the engine's own names, so a setting means the same thing in both products.

Differences from the engine, each on purpose and each tested (tests/test_settings.py):
  * the engine uses None for "this rule is off" (min_qty, min_days_cover); a Float on a Frappe page cannot be empty (an empty one is 0), so 0 means off;
  * `check_cron` is also parsed by croniter, because Frappe's scheduler uses it; the engine only counts the five fields;
  * the time zone is Frappe's own (System Settings), not a second setting.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import getdate

DOCTYPE = "AI Munimji Settings"
EVENTS_FIELD = "calendar_events"


@dataclass(frozen=True)
class Mapped:
	fieldname: str  # on the page; the same as the engine's name
	model: str  # which engine model holds it: "policy", "system" or "calendar"
	kind: str  # "float", "int", "bool" or "text": how the page value becomes the engine's
	zero_is_none: bool = False  # the engine's None ("rule off") is 0 on the page


MAPPED = (
	Mapped("min_qty", "policy", "float", zero_is_none=True),
	Mapped("min_days_cover", "policy", "float", zero_is_none=True),
	Mapped("use_lead_time_rule", "policy", "bool"),
	Mapped("safety_stock_days", "policy", "float"),
	Mapped("default_lead_time_days", "policy", "float"),
	Mapped("recent_window_days", "policy", "int"),
	Mapped("base_window_days", "policy", "int"),
	Mapped("history_days", "policy", "int"),
	Mapped("check_cron", "system", "text"),
	Mapped("approval_expiry_hours", "system", "int"),
	Mapped("reminder_after_hours", "system", "int"),
	Mapped("max_reminders", "system", "int"),
	Mapped("stock_alerts", "system", "bool"),
	Mapped("stock_alert_repeat_days", "system", "int"),
	Mapped("calendar_enabled", "calendar", "bool"),
)
BY_FIELD = {m.fieldname: m for m in MAPPED}

# Fields of the page that the engine knows nothing about. `enabled` is the pack's on/off switch (the standalone keeps it in settings.yaml under packs.enabled, and the pack manifest, in
# the engine, says enabled_by_default: true); `fallback_supplier` is a link to an ERPNext Supplier, which only ERPNext can check.
APP_ONLY = ("enabled", "fallback_supplier", "keep_logs_days")
# The ONE setting where the app deliberately differs from the standalone service: the stock monitor is OFF until a person has reviewed the thresholds and switches it on, so that nothing
# starts creating requests on a customer's live stock at install (docs/NAMES.md). The standalone service keeps the manifest's default, which is on.
ENABLED_DEFAULT = 0
KEEP_LOGS_DEFAULT = 90  # days (retention.py); the clean-up of the logs is the app's own, so the number is too

# The fields of the child table "Munimji Calendar Event" and the engine's CalendarEvent field each one holds.
EVENT_FIELDS = {
	"name": "event_name",
	"kind": "kind",
	"start": "start_date",
	"end": "end_date",
	"uplift_pct": "uplift_pct",
	"note": "note",
}

# The engine reads these models; engine_field == page fieldname except for `calendar_enabled`, which is CalendarSettings.enabled.
ENGINE_NAME = {"calendar_enabled": "enabled"}


def engine_name(fieldname: str) -> str:
	return ENGINE_NAME.get(fieldname, fieldname)


def models():
	"""The engine's models, imported on use so that the app can be loaded (migrated, uninstalled) in a bench where the engine has been removed."""
	try:
		from ai_munimji_engine.packs.stock_procurement.settings import (
			CalendarSettings,
			Policy,
			StockSystemSettings,
		)
	except ImportError:
		frappe.throw(
			_(
				"The rules package ai-munimji-engine is not installed in this bench, so the settings cannot be checked. Install it (see the section The engine in the README) and try again."
			)
		)
	return {"policy": Policy, "system": StockSystemSettings, "calendar": CalendarSettings}


def engine_defaults() -> dict[str, object]:
	"""The engine's default for every mapped field, as the page holds it (None, the engine's "rule off", is 0)."""
	found = {}
	for m in MAPPED:
		default = models()[m.model].model_fields[engine_name(m.fieldname)].default
		found[m.fieldname] = 0 if default is None and m.zero_is_none else default
	return found


def _from_page(m: Mapped, value):
	if value is None:
		# never stored: the page was saved before this field existed (a Single keeps rows only for what was saved; a new field has none until the next save). The engine's own default applies.
		return models()[m.model].model_fields[engine_name(m.fieldname)].default
	if m.kind == "bool":
		return bool(int(value or 0))
	if m.kind == "int":
		return int(value or 0)
	if m.kind == "float":
		number = float(value or 0)
		return None if m.zero_is_none and number == 0 else number
	return (value or "").strip()


def _event_from_page(row) -> dict[str, object]:
	event = {}
	for engine_field, fieldname in EVENT_FIELDS.items():
		value = row.get(fieldname)
		if engine_field in ("start", "end"):
			value = getdate(value) if value else None
		elif engine_field == "uplift_pct":
			value = float(value or 0)
		elif engine_field == "note":
			value = value or ""
		event[engine_field] = value
	return event


def to_engine(doc) -> dict[str, dict]:
	"""What the engine's models are given, from a settings document (or anything with .get)."""
	values: dict[str, dict] = {"policy": {}, "system": {}, "calendar": {}}
	for m in MAPPED:
		values[m.model][engine_name(m.fieldname)] = _from_page(m, doc.get(m.fieldname))
	values["calendar"]["events"] = [_event_from_page(row) for row in doc.get(EVENTS_FIELD) or []]
	return values


def from_engine(values: dict[str, dict]) -> dict[str, object]:
	"""The other way: the page's field values for what the engine's models hold (for example a settings.yaml of the standalone service). The rows of the calendar come as dicts."""
	page: dict[str, object] = {}
	for m in MAPPED:
		value = values[m.model][engine_name(m.fieldname)]
		page[m.fieldname] = 0 if value is None and m.zero_is_none else value
	page[EVENTS_FIELD] = [
		{fieldname: event.get(engine_field) for engine_field, fieldname in EVENT_FIELDS.items()}
		for event in values["calendar"].get("events", [])
	]
	return page


def label_of(fieldname: str) -> str:
	return _(frappe.get_meta(DOCTYPE).get_label(fieldname) or fieldname)


def _event_label(engine_field: str) -> str:
	return _(
		frappe.get_meta("Munimji Calendar Event").get_label(EVENT_FIELDS.get(engine_field, engine_field))
		or engine_field
	)


def _plain(message: str) -> str:
	"""An engine message in the page's words: the engine's own prefix removed and its field names replaced by the labels the person sees."""
	message = message.removeprefix("Value error, ")
	for fieldname in sorted(BY_FIELD, key=len, reverse=True):
		if (
			engine_name(fieldname) == fieldname
		):  # `calendar_enabled` is the engine's plain `enabled`: replacing that word would damage other messages
			message = message.replace(fieldname, f"“{label_of(fieldname)}”")
	return message


def problems(values: dict[str, dict]) -> list[str]:
	"""Every reason the engine gives for refusing these values, in the page's words (an empty list when the engine accepts them)."""
	from pydantic import ValidationError

	found: list[str] = []
	for key, model in models().items():
		try:
			model.model_validate(values[key])
		except ValidationError as exc:
			for error in exc.errors():
				where = error["loc"]
				if where and where[0] == "events":
					row = (
						_("Calendar events, row {0}").format(where[1] + 1)
						if len(where) > 1
						else _("Calendar events")
					)
					field = f", {_event_label(where[2])}" if len(where) > 2 else ""
					found.append(f"{row}{field}: {_plain(error['msg'])}")
				elif where:
					found.append(
						f"{label_of(next((f for f in BY_FIELD if engine_name(f) == where[0]), where[0]))}: {_plain(error['msg'])}"
					)
				else:
					found.append(_plain(error["msg"]))
	return found


def cron_problem(expression: str) -> str | None:
	"""The engine only counts the five fields; Frappe's scheduler reads the expression with croniter, so a schedule it cannot read is refused here."""
	from croniter import croniter

	if not croniter.is_valid(expression):
		return _(
			"{0}: “{1}” is not a schedule the scheduler can read (for example 0 6 * * * is every day at 6 in the morning)"
		).format(label_of("check_cron"), expression)
	return None


def fill_missing(doc) -> None:
	"""Give every setting that has nothing stored its default, before the document is saved. A page saved before a field existed has no row for it (None), and Frappe stores a
	None number as 0 and a None text as empty, which the engine's rules then refuse (found by the tests: tests/test_settings.py)."""
	for fieldname, default in {
		**engine_defaults(),
		"enabled": ENABLED_DEFAULT,
		"keep_logs_days": KEEP_LOGS_DEFAULT,
	}.items():
		if doc.get(fieldname) is None:
			doc.set(fieldname, default)


def validate(doc) -> None:
	"""Refuse the settings with every reason at once. The rules are the engine's; see the top of this module for the two small differences."""
	fill_missing(doc)
	values = to_engine(doc)
	found = problems(values)
	if int(doc.get("keep_logs_days") or 0) < 0:
		found.append(
			_("“{0}” cannot be negative (0 keeps the logs for ever)").format(_("Keep logs for (days)"))
		)
	if not any(
		p.startswith(label_of("check_cron")) for p in found
	):  # the engine has not already complained about it
		bad_cron = cron_problem(values["system"]["check_cron"])
		if bad_cron:
			found.append(bad_cron)
	if found:
		frappe.throw(found, title=_("These settings cannot be saved"), as_list=True)
