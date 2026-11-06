import typing
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase
from pydantic import ValidationError

from ai_munimji import settings_map
from ai_munimji.settings_map import APP_ONLY, BY_FIELD, EVENT_FIELDS, EVENTS_FIELD, MAPPED, engine_name

DOCTYPE = "AI Munimji Settings"
ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ("Section Break", "Column Break", "Tab Break")


def new_page(**values):
	doc = frappe.new_doc(DOCTYPE)
	for fieldname, value in values.items():
		if fieldname == EVENTS_FIELD:
			for row in value:
				doc.append(EVENTS_FIELD, row)
		else:
			doc.set(fieldname, value)
	return doc


def page_accepts(**values) -> bool:
	try:
		new_page(**values).validate()
	except frappe.ValidationError:
		return False
	return True


def engine_defaults() -> dict[str, dict]:
	"""What the standalone service starts from: each engine model with nothing set, written straight from the pydantic models (not through the app's own mapping)."""
	found = {}
	for key, model in settings_map.models().items():
		found[key] = model().model_dump()
	return found


def engine_accepts(values: dict[str, dict]) -> bool:
	for key, model in settings_map.models().items():
		try:
			model.model_validate(values[key])
		except ValidationError:
			return False
	return True


def limits(m) -> dict[str, float]:
	found = {}
	for constraint in settings_map.models()[m.model].model_fields[engine_name(m.fieldname)].metadata:
		for bound in ("ge", "gt", "le", "lt"):
			if hasattr(constraint, bound):
				found[bound] = getattr(constraint, bound)
	return found


def engine_allows_none(m) -> bool:
	"""Asked of the engine's model, not of the app's mapping: does the field accept None ("this rule is off")?"""
	return type(None) in typing.get_args(
		settings_map.models()[m.model].model_fields[engine_name(m.fieldname)].annotation
	)


def candidates(m) -> list:
	"""Values on and just beyond each limit the engine states for the field, and the ones that are always interesting (zero, a negative, the default)."""
	default = settings_map.engine_defaults()[m.fieldname]
	if m.kind == "bool":
		return [True, False]
	if m.kind == "text":
		return ["0 6 * * *", "0 6 * *", "", "0 6 * * * *", "30 7 * * 1", "*/15 * * * *"]
	step = 1 if m.kind == "int" else 0.001
	found = {default, 0, -1, 1}
	for bound, value in limits(m).items():
		found.add(value)
		found.add(value - 1 if bound in ("ge", "lt") else value + 1)
		found.add(value + step if bound == "gt" else value - step if bound == "lt" else value)
	return sorted(int(v) if m.kind == "int" else float(v) for v in found)


class TestTheSettingsAreTheEnginesSettings(IntegrationTestCase):
	"""A value is valid on the settings page exactly when the standalone service accepts it, because the same models decide. These tests compare the two verdicts, value by value,
	starting from the models themselves and not from the app's own mapping."""

	def test_every_mapped_field_is_on_the_page_with_the_engines_default(self):
		meta = frappe.get_meta(DOCTYPE)
		for m in MAPPED:
			field = meta.get_field(m.fieldname)
			self.assertIsNotNone(field, f"{m.fieldname} is mapped but not on the page")
			engine_default = settings_map.engine_defaults()[m.fieldname]
			if m.kind == "bool":
				self.assertEqual(int(field.default or 0), int(engine_default), m.fieldname)
			elif m.kind == "text":
				self.assertEqual(field.default, engine_default, m.fieldname)
			else:
				self.assertEqual(
					float(field.default or 0),
					float(engine_default),
					f"{m.fieldname}: the page starts at {field.default}, the standalone at {engine_default}",
				)

	def test_a_new_page_is_valid_and_the_engine_accepts_what_it_holds(self):
		doc = new_page()
		doc.validate()  # raises if the defaults are not valid
		self.assertEqual(settings_map.problems(settings_map.to_engine(doc)), [])

	def test_the_page_holds_nothing_the_map_does_not_know(self):
		known = set(BY_FIELD) | set(APP_ONLY) | {EVENTS_FIELD}
		on_the_page = {df.fieldname for df in frappe.get_meta(DOCTYPE).fields if df.fieldtype not in LAYOUT}
		self.assertEqual(
			on_the_page - known,
			set(),
			"a field on the page that is neither mapped to the engine nor listed as the app's own would be saved without any check",
		)
		self.assertEqual(known - on_the_page, set(), "listed in the map but not on the page")

	def test_the_engines_field_names_are_the_pages(self):
		for m in MAPPED:
			self.assertIn(engine_name(m.fieldname), settings_map.models()[m.model].model_fields, m.fieldname)
			self.assertEqual(
				m.zero_is_none,
				engine_allows_none(m),
				f"{m.fieldname}: the map and the engine disagree on whether an empty value means 'rule off'",
			)

	def test_the_page_and_the_engine_give_the_same_verdict_on_every_value_at_and_beyond_each_limit(self):
		different, judged, refused = [], 0, {}
		for m in MAPPED:
			for value in candidates(m):
				engine_value = (
					None if engine_allows_none(m) and value == 0 else value
				)  # the one difference: the page cannot be empty, 0 is its "not used"
				values = engine_defaults()
				values[m.model][engine_name(m.fieldname)] = engine_value
				verdicts = (engine_accepts(values), page_accepts(**{m.fieldname: value}))
				judged += 1
				if not verdicts[0]:
					refused[m.fieldname] = refused.get(m.fieldname, 0) + 1
				if verdicts[0] != verdicts[1]:
					different.append(
						f"{m.fieldname}={value!r}: standalone {'accepts' if verdicts[0] else 'refuses'}, page {'accepts' if verdicts[1] else 'refuses'}"
					)
		self.assertEqual(different, [])
		self.assertGreater(judged, 60, "few values were compared: the test would prove little")
		for m in MAPPED:
			if limits(m) or m.kind == "text":
				self.assertGreater(
					refused.get(m.fieldname, 0),
					0,
					f"no refused value was tried for {m.fieldname}: the limits were not found",
				)

	def test_a_rule_that_is_off_is_none_in_the_engine_and_zero_on_the_page(self):
		for fieldname in ("min_qty", "min_days_cover"):
			self.assertIsNone(settings_map.to_engine(new_page(**{fieldname: 0}))["policy"][fieldname])
			self.assertEqual(
				settings_map.from_engine(
					{**engine_defaults(), "policy": {**engine_defaults()["policy"], fieldname: None}}
				)[fieldname],
				0,
			)
			self.assertTrue(page_accepts(**{fieldname: 0}))
		self.assertFalse(page_accepts(min_qty=-1))
		self.assertFalse(page_accepts(min_days_cover=-1))

	def test_rules_that_involve_two_settings_are_the_engines_too(self):
		self.assertFalse(
			page_accepts(recent_window_days=90, base_window_days=90), "recent must be shorter than normal"
		)
		self.assertFalse(
			page_accepts(base_window_days=30, history_days=29), "history must cover the normal-use window"
		)
		self.assertTrue(page_accepts(recent_window_days=7, base_window_days=30, history_days=30))
		values = engine_defaults()
		values["policy"].update(recent_window_days=90, base_window_days=90)
		self.assertFalse(engine_accepts(values))

	def test_the_schedule_is_checked_by_the_engine_and_in_addition_by_croniter(self):
		for expression in ("0 6 * *", "", "0 6 * * * *"):
			self.assertFalse(page_accepts(check_cron=expression), expression)
		# five words, so the engine takes it; the scheduler would not be able to read it
		values = engine_defaults()
		values["system"]["check_cron"] = "99 99 * * *"
		self.assertTrue(engine_accepts(values), "the engine only counts the fields")
		self.assertFalse(
			page_accepts(check_cron="99 99 * * *"),
			"the page also asks croniter, which Frappe's scheduler uses",
		)

	def test_what_the_standalone_accepts_loads_into_the_page_and_comes_back_unchanged(self):
		values = engine_defaults()
		values["policy"].update(
			min_qty=25.0,
			min_days_cover=None,
			use_lead_time_rule=False,
			safety_stock_days=2.5,
			default_lead_time_days=10.0,
			recent_window_days=7,
			base_window_days=60,
			history_days=365,
		)
		values["system"].update(
			check_cron="30 7 * * 1",
			approval_expiry_hours=48,
			reminder_after_hours=12,
			max_reminders=0,
			stock_alerts=False,
			stock_alert_repeat_days=14,
		)
		values["calendar"].update(
			enabled=False,
			events=[
				{
					"name": "Diwali sale",
					"kind": "festival",
					"start": "2026-11-08",
					"end": "2026-11-12",
					"uplift_pct": 40.0,
					"note": "all stores",
				}
			],
		)
		self.assertTrue(engine_accepts(values), "the sample is valid for the standalone")

		doc = new_page(**settings_map.from_engine(values))
		doc.validate()
		back = settings_map.to_engine(doc)
		for key in ("policy", "system"):
			for field, value in values[key].items():
				if field in {engine_name(m.fieldname) for m in MAPPED if m.model == key}:
					self.assertEqual(back[key][field], value, f"{key}.{field}")
		self.assertIs(back["calendar"]["enabled"], False)
		event = back["calendar"]["events"][0]
		self.assertEqual(
			(event["name"], event["kind"], str(event["start"]), str(event["end"]), event["uplift_pct"]),
			("Diwali sale", "festival", "2026-11-08", "2026-11-12", 40.0),
		)

	def test_calendar_events_follow_the_engines_rules_and_say_which_row(self):
		row = {
			"event_name": "Sale",
			"kind": "promotion",
			"start_date": "2026-11-08",
			"end_date": "2026-11-12",
			"uplift_pct": 20,
		}
		self.assertTrue(page_accepts(calendar_events=[row]))
		with self.assertRaises(frappe.ValidationError) as ended_before_it_began:
			new_page(calendar_events=[row, {**row, "end_date": "2026-11-01"}]).validate()
		self.assertIn("row 2", str(ended_before_it_began.exception))
		self.assertFalse(
			page_accepts(calendar_events=[{**row, "uplift_pct": -100}]), "a change of -100% is not a change"
		)
		self.assertTrue(page_accepts(calendar_events=[{**row, "uplift_pct": -99.5}]))
		self.assertFalse(page_accepts(calendar_events=[{**row, "event_name": "x" * 81}]))
		self.assertFalse(page_accepts(calendar_events=[{**row, "kind": "party"}]))
		self.assertEqual(
			set(EVENT_FIELDS.values()),
			{df.fieldname for df in frappe.get_meta("Munimji Calendar Event").fields},
			"every column of the table is an engine field",
		)

	def test_a_refusal_names_the_setting_by_the_words_on_the_page(self):
		with self.assertRaises(frappe.ValidationError) as refused:
			new_page(approval_expiry_hours=0, max_reminders=11).validate()
		message = str(refused.exception)
		self.assertIn("A request expires after", message)
		self.assertIn("Most reminders for one request", message)
		self.assertNotIn(
			"approval_expiry_hours", message, "the engine's field name is not for the person at the page"
		)

	def test_a_valid_page_saves_and_reads_back(self):
		self.addCleanup(frappe.db.rollback)  # the page is a Single: leave the site's settings as they were
		doc = frappe.get_doc(DOCTYPE)
		doc.min_qty, doc.max_reminders = 25, 3
		doc.append(
			EVENTS_FIELD,
			{
				"event_name": "Sale",
				"kind": "promotion",
				"start_date": "2026-11-08",
				"end_date": "2026-11-12",
				"uplift_pct": 20,
			},
		)
		doc.save()
		again = frappe.get_doc(DOCTYPE)
		self.assertEqual((again.min_qty, again.max_reminders, len(again.calendar_events)), (25, 3, 1))
		again.max_reminders = 99
		with self.assertRaises(frappe.ValidationError):
			again.save()
		self.assertEqual(frappe.get_doc(DOCTYPE).max_reminders, 3, "a refused save changes nothing")

	def test_a_page_saved_before_a_field_existed_gets_the_engines_default_for_it(self):
		# A Single keeps rows only for what was saved: after an upgrade that adds a field, a page saved earlier has nothing for it (None), which must not read as 0.
		doc = frappe.new_doc(DOCTYPE)
		for m in MAPPED:
			doc.set(m.fieldname, None)
		doc.validate()
		self.assertEqual(settings_map.problems(settings_map.to_engine(doc)), [])
		self.assertEqual(settings_map.to_engine(doc)["system"]["approval_expiry_hours"], 72)
		self.assertIsNone(settings_map.to_engine(doc)["policy"]["min_qty"])
		self.assertEqual(settings_map.to_engine(doc)["policy"]["min_days_cover"], 7.0)

	def test_saving_a_page_that_has_nothing_stored_for_a_field_stores_the_default_and_not_zero(self):
		# Found by the job tests: a Single saved before a field existed has no row for it; Frappe turns that None into 0 on save, and the next load then fails the engine's rules.
		self.addCleanup(frappe.db.rollback)
		frappe.get_doc(
			DOCTYPE
		).save()  # the page exists, as on a site where someone has opened and saved it...
		frappe.db.delete(
			"Singles", {"doctype": DOCTYPE, "field": ["in", [m.fieldname for m in MAPPED]]}
		)  # ...before these fields existed
		frappe.clear_document_cache(DOCTYPE, DOCTYPE)
		doc = frappe.get_doc(DOCTYPE)
		self.assertIsNone(doc.approval_expiry_hours, "nothing is stored for it")
		doc.enabled = 0
		doc.save()
		stored = frappe.db.get_singles_dict(DOCTYPE)
		self.assertEqual(
			(
				int(stored["approval_expiry_hours"]),
				int(stored["max_reminders"]),
				float(stored["min_days_cover"]),
				stored["check_cron"],
			),
			(72, 2, 7.0, "0 6 * * *"),
		)
		self.assertEqual(frappe.get_doc(DOCTYPE).validate(), None)

	def test_the_stock_monitor_is_off_by_default_on_purpose_and_the_standalone_keeps_its_own_default(self):
		from ai_munimji_engine.packs.stock_procurement.manifest import manifest

		self.assertEqual(frappe.get_meta(DOCTYPE).get_field("enabled").default, "0")
		self.assertEqual(settings_map.ENABLED_DEFAULT, 0)
		self.assertEqual(new_page().enabled, 0, "a new page shows Watch stock unchecked")
		self.assertTrue(
			manifest().enabled_by_default,
			"the standalone service keeps its default, which is on: the app differs on purpose",
		)
		names = (ROOT / "docs" / "NAMES.md").read_text(encoding="utf-8")
		self.assertIn(
			"deliberately differs",
			names,
			"docs/NAMES.md must say that the app differs from the manifest here, and why",
		)
		self.assertIn("live stock", names)

	def test_a_site_that_never_stored_the_switch_has_it_off(self):
		self.addCleanup(frappe.db.rollback)
		frappe.get_doc(DOCTYPE).save()
		frappe.db.delete(
			"Singles", {"doctype": DOCTYPE, "field": "enabled"}
		)  # a page saved before the switch existed
		frappe.clear_document_cache(DOCTYPE, DOCTYPE)
		doc = frappe.get_doc(DOCTYPE)
		self.assertFalse(doc.enabled, "nothing stored reads as off")
		doc.save()
		self.assertEqual(
			int(frappe.db.get_singles_dict(DOCTYPE)["enabled"]),
			0,
			"saving the page must not switch the monitor on",
		)

	def test_the_page_holds_no_secret(self):
		# Version 0.1 has none. A Password field would need the proof that its value is neither in the table nor in the version log (the spike did it once, in the report);
		# this test fails the day one is added, so that the proof is written then.
		for doctype in (DOCTYPE, "Munimji Calendar Event"):
			passwords = [df.fieldname for df in frappe.get_meta(doctype).fields if df.fieldtype == "Password"]
			self.assertEqual(
				passwords,
				[],
				f"{doctype} has a Password field: add the test that its value is not logged first",
			)
		self.assertEqual(frappe.db.sql("SELECT COUNT(*) FROM `__Auth` WHERE doctype = %s", DOCTYPE)[0][0], 0)
