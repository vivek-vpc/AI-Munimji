"""What Frappe does with the values the engine's stores write, found out on the real database before anything is built on it (Phase 4b, docs/STORE_PROBES.md).

It makes two throw-away DocTypes ("Munimji Probe", "Munimji Probe Counter"; custom, so no file is written into the app), runs the probes, prints one JSON report and removes both.
Development tooling: it runs as Administrator on the development site and is not part of the app.
    .\\dev\\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/probe_stores.py
"""

import json
import threading
import time
import traceback

import frappe
from frappe.utils import get_system_timezone

SITE = frappe.local.site
P1 = "Munimji Probe"
P2 = "Munimji Probe Counter"
REPORT = {}


def probe(name):
	def wrap(fn):
		try:
			REPORT[name] = fn()
		except Exception as exc:
			REPORT[name] = {
				"ERROR": f"{type(exc).__name__}: {str(exc)[:300]}",
				"where": traceback.format_exc()[-400:],
			}
		return fn

	return wrap


def field(fieldname, fieldtype, **kw):
	return {"fieldname": fieldname, "fieldtype": fieldtype, "label": fieldname, **kw}


def make_doctypes():
	for dt in (P1, P2):
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, force=1)
	for dt in (P1, P2):
		frappe.db.sql_ddl(f"drop table if exists `tab{dt}`")
	frappe.db.commit()
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": P1,
			"module": "AI Munimji",
			"custom": 1,
			"autoname": "Prompt",
			"fields": [
				field("f_float", "Float"),
				field("f_int", "Int"),
				field("f_cur", "Currency"),
				field("f_dt", "Datetime"),
				field("f_date", "Date"),
				field("f_check", "Check"),
				field("f_data", "Data", search_index=1),
				field("f_link", "Link", options="Item"),
				field("f_select", "Select", options="\nA\nB"),
				field("f_json", "JSON"),
				field("f_long", "Long Text"),
				field("f_code", "Code", options="JSON"),
				field("f_small", "Small Text"),
				field("f_uniq", "Data", unique=1),
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		}
	).insert()
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": P2,
			"module": "AI Munimji",
			"custom": 1,
			"autoname": "autoincrement",
			"naming_rule": "Autoincrement",
			"fields": [field("f_data", "Data")],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		}
	).insert()
	frappe.db.commit()


def new(doctype, name=None, **values):
	doc = frappe.get_doc({"doctype": doctype, **values})
	if name is not None:
		doc.flags.name_set = True
		doc.name = name
	return doc.insert()


def own_connection(fn):
	"""Run fn(result_dict) on its own thread with its own database connection; returns the thread and the dict."""
	out = {}

	def run():
		try:
			frappe.init(site=SITE)
			frappe.connect()
			frappe.set_user("Administrator")
			fn(out)
		except Exception as exc:
			out["ERROR"] = f"{type(exc).__name__}: {str(exc)[:200]}"
		finally:
			try:
				frappe.db.rollback()
				frappe.destroy()
			except Exception:
				pass

	t = threading.Thread(target=run)
	t.start()
	return t, out


make_doctypes()


@probe("none_and_empty")
def _():
	out = {}
	new(
		P1,
		"n1",
		f_float=None,
		f_int=None,
		f_cur=None,
		f_dt=None,
		f_date=None,
		f_check=None,
		f_data=None,
		f_link=None,
		f_select=None,
		f_json=None,
		f_long=None,
		f_small=None,
	)
	frappe.db.commit()
	doc = frappe.get_doc(P1, "n1")
	row = frappe.get_list(P1, filters={"name": "n1"}, fields=["*"])[0]
	raw = frappe.db.sql(
		"select f_float, f_int, f_cur, f_dt, f_date, f_check, f_data, f_link, f_select, f_json, f_long, f_small from `tabMunimji Probe` where name='n1'",
		as_dict=True,
	)[0]
	for k in (
		"f_float",
		"f_int",
		"f_cur",
		"f_dt",
		"f_date",
		"f_check",
		"f_data",
		"f_link",
		"f_select",
		"f_json",
		"f_long",
		"f_small",
	):
		out[k] = {"get_doc": repr(doc.get(k)), "get_list": repr(row.get(k)), "raw_db": repr(raw.get(k))}
	new(P1, "e1", f_data="", f_long="", f_small="", f_link="")
	frappe.db.commit()
	e = frappe.get_list(P1, filters={"name": "e1"}, fields=["f_data", "f_long", "f_small", "f_link"])[0]
	out["empty_strings_after_insert_get_list"] = {k: repr(v) for k, v in e.items()}
	# a value set to None after being something
	d = frappe.get_doc(P1, "e1")
	d.f_float = 2.5
	d.save()
	d.f_float = None
	d.save()
	frappe.db.commit()
	try:
		new(P1, "e2", f_json="")
		out["json_empty_string"] = "inserted"
	except Exception as exc:
		out["json_empty_string"] = type(exc).__name__
	frappe.db.rollback()
	out["float_set_then_None_get_list"] = repr(
		frappe.get_list(P1, filters={"name": "e1"}, fields=["f_float"])[0]["f_float"]
	)
	out["float_set_then_None_raw"] = repr(
		frappe.db.sql("select f_float from `tabMunimji Probe` where name='e1'")[0][0]
	)
	return out


@probe("json_text_exact")
def _():
	out = {}
	samples = {
		"spaces": '{"b": 1,  "a": "é\\u2028 x"}\n',
		"order": '{"z": 1, "a": 2, "m": [3, 2, 1]}',
		"unicode": json.dumps({"naïve": "日本語 ✓ 🙂", "tax": 1.10}, ensure_ascii=False),
		"nonjson": "not json at all",
		"empty_object": "{}",
		"big": json.dumps({"reasoning": "x" * 2_000_000}),
	}
	for label, text in samples.items():
		for fieldname in ("f_json", "f_long", "f_code"):
			key = f"{label}/{fieldname}"
			try:
				name = f"j-{label}-{fieldname}"
				new(P1, name, **{fieldname: text})
				frappe.db.commit()
				via_doc = frappe.get_doc(P1, name).get(fieldname)
				via_list = frappe.get_list(P1, filters={"name": name}, fields=[fieldname])[0][fieldname]
				out[key] = {
					"get_doc_exact": via_doc == text,
					"get_list_exact": via_list == text,
					"type": type(via_list).__name__,
					"length": len(text),
				}
			except Exception as exc:
				out[key] = {"ERROR": f"{type(exc).__name__}: {str(exc)[:160]}"}
	return out


@probe("datetime")
def _():
	out = {"system_timezone": get_system_timezone()}
	new(P1, "d1", f_dt="2026-10-16 08:00:00.123456", f_date="2026-10-16")
	new(P1, "d2", f_dt="2026-10-16 08:00:00")
	frappe.db.commit()
	rows = frappe.get_list(
		P1,
		filters={"name": ["in", ["d1", "d2"]]},
		fields=["name", "f_dt", "f_date", "creation"],
		order_by="name",
	)
	out["get_list"] = [{k: repr(v) for k, v in r.items()} for r in rows]
	out["get_doc_f_dt"] = repr(frappe.get_doc(P1, "d1").f_dt)
	out["raw_column_type"] = frappe.db.sql(
		"select column_type from information_schema.columns where table_name='tabMunimji Probe' and column_name='f_dt' and table_schema=database()"
	)[0][0]
	out["filter_range"] = [
		r.name
		for r in frappe.get_list(P1, filters={"f_dt": [">=", "2026-10-16 08:00:00.5"]}, fields=["name"])
	]
	out["filter_between_text"] = [
		r.name
		for r in frappe.get_list(
			P1, filters={"f_dt": ["<", "2026-10-16T09:00:00"]}, fields=["name"], order_by="name"
		)
	]
	return out


@probe("collation_and_keys")
def _():
	out = {
		"name_collation": frappe.db.sql(
			"select collation_name from information_schema.columns where table_name='tabMunimji Probe' and column_name='name' and table_schema=database()"
		)[0][0]
	}
	new(P1, "AbC", f_data="BOLT-é")
	frappe.db.commit()
	try:
		new(P1, "abc")
		out["names_differing_only_in_case"] = "both inserted"
	except Exception as exc:
		out["names_differing_only_in_case"] = type(exc).__name__
	frappe.db.rollback()
	out["filter_f_data_bolt-e"] = [
		r.name for r in frappe.get_list(P1, filters={"f_data": "bolt-e"}, fields=["name"])
	]
	out["like_accent"] = [
		r.name for r in frappe.get_list(P1, filters={"f_data": ["like", "%bolt-E%"]}, fields=["name"])
	]
	out["trailing_space_match"] = [
		r.name for r in frappe.get_list(P1, filters={"f_data": "BOLT-é "}, fields=["name"])
	]
	try:
		new(P1, "x" * 200)
		out["name_200_chars"] = "inserted"
	except Exception as exc:
		out["name_200_chars"] = f"{type(exc).__name__}: {str(exc)[:120]}"
	frappe.db.rollback()
	try:
		new(P1, "u1", f_uniq="same")
		frappe.db.commit()
		new(P1, "u2", f_uniq="same")
		out["unique_field"] = "both inserted"
	except Exception as exc:
		out["unique_field"] = type(exc).__name__
	frappe.db.rollback()
	return out


@probe("autoincrement")
def _():
	out = {}
	a = new(P2, f_data="one")
	b = new(P2, f_data="two")
	c = new(P2, f_data="three")
	frappe.db.commit()
	out["names"] = [repr(a.name), repr(b.name), repr(c.name)]
	out["get_doc_by_int"] = frappe.get_doc(P2, int(b.name)).f_data
	out["get_doc_by_str"] = frappe.get_doc(P2, str(b.name)).f_data
	out["order_by_name_desc"] = [
		repr(r.name) for r in frappe.get_list(P2, fields=["name"], order_by="name desc")
	]
	frappe.delete_doc(P2, str(c.name), force=1)
	frappe.db.commit()
	d = new(P2, f_data="four")
	frappe.db.commit()
	out["after_delete_next_name"] = repr(d.name)
	out["name_column_type"] = frappe.db.sql(
		"select column_type from information_schema.columns where table_name='tabMunimji Probe Counter' and column_name='name' and table_schema=database()"
	)[0][0]
	return out


@probe("savepoint")
def _():
	out = {}
	frappe.db.savepoint("probe_sp")
	new(P1, "sp1", f_data="inside")
	out["inside_before_rollback"] = frappe.db.exists(P1, "sp1") is not None
	frappe.db.rollback(save_point="probe_sp")
	out["after_rollback_to_savepoint"] = frappe.db.exists(P1, "sp1") is not None
	frappe.db.savepoint("probe_sp2")
	new(P1, "sp2", f_data="kept")
	frappe.db.release_savepoint("probe_sp2") if hasattr(frappe.db, "release_savepoint") else None
	out["released_row_still_there"] = frappe.db.exists(P1, "sp2") is not None
	return out


@probe("aggregates_in_get_list")
def _():
	new(P1, "g1", f_data="grp", f_float=1.5)
	new(P1, "g2", f_data="grp", f_float=2.5)
	frappe.db.commit()
	rows = frappe.get_list(
		P1,
		filters={"f_data": "grp"},
		fields=[
			"f_data",
			{"COUNT": "name", "as": "n"},
			{"SUM": "f_float", "as": "s"},
			{"MAX": "creation", "as": "latest"},
		],
		group_by="f_data",
	)
	return [{k: repr(v) for k, v in r.items()} for r in rows]


@probe("isolation_and_row_locks")
def _():
	out = {}
	new(P1, "iso0", f_data="start")
	frappe.db.commit()
	out["isolation"] = frappe.db.sql("select @@transaction_isolation")[0][0]
	out["innodb_lock_wait_timeout"] = frappe.db.sql("select @@innodb_lock_wait_timeout")[0][0]

	# 1. a second connection that already read something does not see a row committed afterwards, unless it asks for a locking read
	b_ready, a_done = threading.Event(), threading.Event()

	def conn_b(res):
		frappe.db.get_value(P1, "iso0", "f_data")  # opens B's snapshot
		b_ready.set()
		a_done.wait(10)
		res["plain_get_list_sees_it"] = bool(frappe.get_list(P1, filters={"name": "iso1"}, fields=["name"]))
		res["get_value_for_update_sees_it"] = (
			frappe.db.get_value(P1, "iso1", "name", for_update=True) is not None
		)
		try:
			res["get_doc_for_update_sees_it"] = bool(frappe.get_doc(P1, "iso1", for_update=True))
		except Exception as exc:
			res["get_doc_for_update_sees_it"] = f"{type(exc).__name__}"

	tb, rb = own_connection(conn_b)
	b_ready.wait(10)

	def conn_a(res):
		new(P1, "iso1", f_data="later")
		frappe.db.commit()
		res["committed"] = True

	ta, ra = own_connection(conn_a)
	ta.join(15)
	a_done.set()
	tb.join(15)
	out["snapshot_test"] = {"B": rb, "A": ra}

	# 2. get_doc(for_update=True) makes a second connection wait until the first commits
	locked = threading.Event()

	def holder(res):
		frappe.get_doc(P1, "iso0", for_update=True)
		locked.set()
		time.sleep(2.0)
		frappe.db.commit()
		res["released_at"] = time.time()

	th, rh = own_connection(holder)
	locked.wait(10)

	def waiter(res):
		start = time.time()
		frappe.get_doc(P1, "iso0", for_update=True)
		res["waited_seconds"] = round(time.time() - start, 2)

	tw, rw = own_connection(waiter)
	tw.join(20)
	th.join(20)
	out["row_lock_wait"] = {"holder": rh, "waiter": rw}

	# 3. two inserts of one name: the second waits for the first's commit, then fails with a duplicate error
	first_in = threading.Event()

	def inserter(res):
		new(P1, "race1", f_data="first")
		first_in.set()
		time.sleep(2.0)
		frappe.db.commit()
		res["first_committed"] = True

	ti, ri = own_connection(inserter)
	first_in.wait(10)

	def second_inserter(res):
		start = time.time()
		try:
			new(P1, "race1", f_data="second")
			res["second"] = "inserted"
		except Exception as exc:
			res["second"] = type(exc).__name__
		res["waited_seconds"] = round(time.time() - start, 2)

	t2, r2 = own_connection(second_inserter)
	t2.join(20)
	ti.join(20)
	out["duplicate_insert"] = {"first": ri, "second": r2}
	return out


@probe("permission_filters")
def _():
	# what get_list does for a user who may only "select" (the 4a finding) is covered by the app's tests; here only that Administrator passes
	return {"administrator_get_list_ok": isinstance(frappe.get_list(P1, limit_page_length=1), list)}


for dt in (P1, P2):
	try:
		frappe.delete_doc("DocType", dt, force=1)
	except Exception as exc:
		REPORT[f"cleanup {dt}"] = str(exc)[:200]
	frappe.db.sql_ddl(f"drop table if exists `tab{dt}`")
frappe.db.commit()
print("PROBE-REPORT-START")
print(json.dumps(REPORT, indent=1, default=str, ensure_ascii=False))
print("PROBE-REPORT-END")
