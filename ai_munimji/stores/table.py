"""One engine table on one DocType: rows in, rows out.

The stores (core.py, stock.py) say what the engine means; this says how a Frappe record holds it. It never takes a shortcut around Frappe's own checks: a person's session reads with
`get_list` after an explicit read-right check, writes through the document API (so the DocType's permission rows decide), and takes a row lock (`for_update`) before it changes a record.
`ignore_permissions` and raw queries do not appear here. The Administrator (the scheduled job) passes the same checks because Frappe lets it.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import frappe
from frappe import _

from ai_munimji.stores import convert, locks, missing
from ai_munimji.stores.specs import BY_ENGINE, Col, Table

Row = dict[str, Any]
Project = Callable[[Row], dict[str, Any]]
UNBOUNDED = (
	1_000_000  # get_list with no limit at all is not what it looks like: ask for a number nobody reaches
)


class Exists(ValueError):
	"""A record with this name exists already (the engine's tables have a primary key; so does this)."""


class DocTable:
	def __init__(self, engine_table: str, project: Project | None = None) -> None:
		self.spec: Table = BY_ENGINE[engine_table]
		self.doctype = self.spec.doctype
		self.project = project
		self.has_nulls = any(c.null for c in self.spec.cols)
		self.columns = {c.name: c for c in self.spec.cols}
		self.internal = {c.name for c in self.spec.cols if c.internal}
		self.key = self.spec.key[0]
		extra = [self.key] if self.spec.numbered else []
		extra += ["row_json"] if self.spec.json_row else []
		extra += ["nulls"] if self.has_nulls else []
		self.fields = ["name", *self.columns, *extra]

	# ------------------------------------------------------------------ rights
	def need(self, right: str) -> None:
		"""The person must hold `right` on this DocType at all; said plainly, because Frappe's own error for it can be empty."""
		if not frappe.has_permission(self.doctype, right):
			raise frappe.PermissionError(
				_("{0} may not {1} {2} records (the DocType's permission rows decide).").format(
					frappe.session.user, right, self.doctype
				)
			)

	# ------------------------------------------------------------------ names
	def name_of(self, row: Row) -> str:
		if self.spec.numbered:
			return str(int(row[self.key]))
		if self.spec.hashed:
			return convert.hashed_name(*(row.get(k) for k in self.spec.key))
		return convert.plain_name(row[self.key])

	# ------------------------------------------------------------------ one value, each way
	def _into(self, col: Col, raw: Any, zone) -> tuple[Any, bool]:
		"""The engine's value as the field's, and whether it was an empty number (kept in `nulls`)."""
		kind = col.kind
		if kind in ("data", "text", "long"):
			if raw is None:
				return None, False
			raw = str(raw)
			return (convert.clip(raw) if kind == "data" and self.spec.json_row else raw), False
		if kind == "json":
			return raw, False
		if kind == "int":
			return int(raw or 0), False
		if kind == "float":
			return (0.0, True) if raw is None else (float(raw), False)
		if kind == "check":
			return int(bool(raw)), False
		if kind == "datetime":
			return convert.to_datetime(raw, zone), False
		if kind == "date":
			return convert.to_date(raw), False
		raise ValueError(f"unknown kind {kind}")

	def _out(self, col: Col, value: Any, empty: bool = False) -> Any:
		kind = col.kind
		if kind == "int":
			return int(value or 0)
		if kind == "float":
			return None if empty else float(value or 0)
		if kind == "check":
			return int(bool(value))
		if kind == "datetime":
			return convert.from_datetime(value)
		if kind == "date":
			return convert.from_date(value)
		return value

	def values(self, row: Row) -> dict[str, Any]:
		"""The fields of the record for this engine row."""
		zone = convert.site_zone()
		derived = self.project(row) if self.project else {}
		values: dict[str, Any] = {}
		empties: list[str] = []
		if self.spec.numbered:
			values[self.key] = int(row[self.key])
		for col in self.spec.cols:
			if col.internal:
				continue  # the app's own bookkeeping beside the row: a write of the row leaves it as it is
			raw = derived.get(col.name) if col.derived else row.get(col.name)
			values[col.name], empty = self._into(col, raw, zone)
			if empty and col.null:
				empties.append(col.name)
		if self.has_nulls:
			values["nulls"] = json.dumps(empties) if empties else None
		if self.spec.json_row:
			values["row_json"] = convert.row_json(row)
		return values

	def row(self, record: Any) -> Row:
		"""The engine row held by a record (a document or a get_list row)."""
		get = record.get
		if self.spec.json_row:
			return json.loads(get("row_json"))
		empties = set(json.loads(get("nulls") or "[]")) if self.has_nulls else set()
		row: Row = {}
		if self.spec.numbered:
			row[self.key] = int(get(self.key))
		elif not self.spec.hashed:
			row[self.key] = get("name")
		for col in self.spec.cols:
			if not (col.derived or col.internal):
				row[col.name] = self._out(col, get(col.name), col.name in empties)
		return row

	# ------------------------------------------------------------------ writing
	def insert(self, row: Row) -> Row:
		"""Make the record. A numbered table gives the row its number here. A name that is taken raises `Exists`."""
		row = dict(row)
		if self.spec.numbered:
			row[self.key] = locks.next_number(self.doctype)
		name = self.name_of(row)
		doc = frappe.get_doc({"doctype": self.doctype, **self.values(row)})
		doc.flags.name_set = True
		doc.flags.munimji_store = True  # see stores/record.py
		doc.name = name
		doc.flags.ignore_links = (
			True  # a Link here is a pointer for the Desk; the engine's ids need not exist in ERPNext
		)
		try:
			doc.insert()
		except frappe.DuplicateEntryError:
			raise Exists(f"{self.doctype} {name} exists") from None
		return row

	def change(self, name: str, fn: Callable[[Row], Row | None]) -> Row | None:
		"""Under a row lock, let `fn` change the row it is given and return it (or None to leave the record as it is). Returns the new row; None when there is no such record or
		`fn` declined."""
		try:
			doc = frappe.get_doc(self.doctype, name, for_update=True)
		except frappe.DoesNotExistError:
			missing.not_there()
			return None
		new = fn(self.row(doc))
		if new is None:
			return None
		doc.update(self.values(new))
		doc.flags.munimji_store = True
		doc.flags.ignore_links = True
		doc.save()
		return new

	def set_internal(self, name: str, **values: Any) -> bool:
		"""Under a row lock, set the app's own columns (`internal` in the spec) of the record, and nothing else. The engine's row is not touched, so a digest over it does not change.
		False when there is no such record."""
		unknown = set(values) - self.internal
		if unknown:
			raise KeyError(f"{self.doctype} has no internal column {sorted(unknown)}")
		try:
			doc = frappe.get_doc(self.doctype, name, for_update=True)
		except frappe.DoesNotExistError:
			missing.not_there()
			return False
		for key, value in values.items():
			doc.set(key, self._into(self.columns[key], value, convert.site_zone())[0])
		doc.flags.munimji_store = True
		doc.flags.ignore_links = True
		doc.save()
		return True

	def internal_values(self, name: str) -> dict[str, Any] | None:
		"""The app's own columns of a record, as the signed-in person may read them (the engine's row has none of them), or None when there is no such record."""
		self.need("read")
		rows = frappe.get_list(
			self.doctype, fields=sorted(self.internal), filters={"name": name}, limit_page_length=1
		)
		return dict(rows[0]) if rows else None

	def put(self, row: Row) -> bool:
		"""Make the record, or replace what is there. True when it was made."""
		try:
			self.insert(row)
			return True
		except Exists:
			self.change(self.name_of(row), lambda _old: dict(row))
			return False

	def remove(self, name: str) -> bool:
		"""Delete the record (the person must hold the delete right). False when there is none."""
		self.need("delete")
		try:
			doc = frappe.get_doc(self.doctype, name, for_update=True)
		except frappe.DoesNotExistError:
			missing.not_there()
			return False
		doc.flags.munimji_store = True
		doc.delete()
		return True

	# ------------------------------------------------------------------ reading
	def get(self, name: str) -> Row | None:
		self.need("read")
		try:
			doc = frappe.get_doc(self.doctype, name)
		except frappe.DoesNotExistError:
			missing.not_there()
			return None
		doc.check_permission("read")
		return self.row(doc)

	def find(
		self,
		filters: Sequence[Sequence[Any]] | None = None,
		or_filters: Sequence[Sequence[Any]] | None = None,
		order_by: str = "",
		limit: int = 0,
	) -> list[Row]:
		self.need("read")
		records = frappe.get_list(
			self.doctype,
			fields=self.fields,
			filters=list(filters or []),
			or_filters=list(or_filters or []),
			order_by=order_by or "creation asc",
			limit_page_length=limit or UNBOUNDED,
		)
		return [self.row(r) for r in records]

	def select(
		self,
		columns: Sequence[str],
		filters: Sequence[Sequence[Any]] | None = None,
		order_by: str = "",
		limit: int = 0,
	) -> list[Row]:
		"""Only these columns (as the engine's values), and `name`; for the lists and totals that must not read every row's JSON."""
		self.need("read")
		for c in columns:
			if c not in self.columns and c != self.key:
				raise KeyError(f"{self.doctype} has no column {c}")
		records = frappe.get_list(
			self.doctype,
			fields=["name", *columns],
			filters=list(filters or []),
			order_by=order_by or "creation asc",
			limit_page_length=limit or UNBOUNDED,
		)
		out = []
		for r in records:
			got: Row = {"name": r.name}
			for c in columns:
				col = self.columns.get(c)
				got[c] = self._out(col, r.get(c)) if col else r.get(c)
			out.append(got)
		return out

	def names(
		self, filters: Sequence[Sequence[Any]] | None = None, order_by: str = "", limit: int = 0
	) -> list[str]:
		return [r["name"] for r in self.select([], filters, order_by, limit)]

	def count(self, filters: Sequence[Sequence[Any]] | None = None) -> int:
		self.need("read")
		rows = frappe.get_list(
			self.doctype,
			fields=[{"COUNT": "name", "as": "n"}],
			filters=list(filters or []),
		)
		return int(rows[0]["n"]) if rows else 0

	def at(self, text: str | None) -> str | None:
		"""An engine moment as text for a filter on a Datetime column."""
		moment = convert.to_datetime(text)
		return moment.strftime("%Y-%m-%d %H:%M:%S.%f") if moment else None
