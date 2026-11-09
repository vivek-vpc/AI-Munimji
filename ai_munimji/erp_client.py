"""The engine's stock port, answered by the Frappe site the app runs on: in process, as the signed-in user.

`FrappeERPClient` implements `ai_munimji_engine.packs.stock_procurement.erp.StockProcurementERP` (and the optional parts the stock rules use). Compared with the standalone service's
REST client (`ERPNextClient`) there is no HTTP and no service account:

* every read is `frappe.get_list`, so Frappe applies the signed-in person's own permissions; a person who may not read a DocType gets `frappe.PermissionError`, never rows;
* every document is made with `frappe.get_doc(...).insert()` as that person, never submitted, with the request's reference in `custom_agent_ref` and the approver in
  `custom_agent_approved_by`, the same two fields the standalone service writes (ai_munimji/custom_fields.py);
* nothing here uses `get_all`, `ignore_permissions` or a raw `frappe.db` read (ai_munimji/tests/test_rules.py fails if it does).

The one exception is a mode, not a loophole: `FrappeERPClient(system=True)`, accepted only while the session is Administrator, is how the scheduled job (which Frappe runs as
Administrator) says that it reads what a person may not, the Tax Rules in particular. It is constructed in `ai_munimji/jobs.py` and nowhere else (also enforced by the test).

Part of the port is left out of this version and raises `NotSupportedInThisVersion` (docs/KNOWN_LIMITATIONS.md): the purchasing follow-up and stock-intelligence reads, and everything
that sends a message to a supplier.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import frappe
from ai_munimji_engine.core.erp.base import FoundDocument
from ai_munimji_engine.packs.stock_procurement.erp import (
	STOCK_COLUMNS,
	DailyUsage,
	ItemInfo,
	PurchaseOrderDraft,
	PurchaseOrderResult,
	QuoteRule,
	RequisitionDraft,
	SalesDue,
	StockInfo,
	StockTransferDraft,
	TaxRow,
	TaxSetup,
	VendorOffer,
	WarehouseStock,
)
from frappe import _
from frappe.utils import nowtime

from ai_munimji.custom_fields import APPROVED_BY, NOTE, REF
from ai_munimji.stores import locks

FINISHED = ["Completed", "Closed", "Cancelled", "Delivered"]
CONSUMPTION_VOUCHERS = ["Delivery Note", "Sales Invoice"]
# the fields of a rule that depend on addresses or items, which cannot be judged without the order's own addresses (as in the REST client)
UNJUDGEABLE_RULE_FIELDS = [
	"billing_city", "billing_county", "billing_state", "billing_zipcode", "billing_country",
	"shipping_city", "shipping_county", "shipping_state", "shipping_zipcode", "shipping_country", "item", "item_group",
]  # fmt: skip
# what each readable document looks like to the chat and to the order checks (get_documents)
DOC_SPECS = {
	"Purchase Order": dict(
		child="Purchase Order Item",
		party="supplier_name",
		party_id="supplier",
		date="transaction_date",
		due="schedule_date",
		total="grand_total",
		currency="currency",
		done="received_qty",
		per_received="per_received",
		per_billed="per_billed",
		kind=None,
	),
	"Material Request": dict(
		child="Material Request Item",
		party=None,
		party_id=None,
		date="transaction_date",
		due="schedule_date",
		total=None,
		currency=None,
		done="ordered_qty",
		per_received="per_received",
		per_billed=None,
		kind="material_request_type",
	),
	"Purchase Receipt": dict(
		child="Purchase Receipt Item",
		party="supplier_name",
		party_id="supplier",
		date="posting_date",
		due=None,
		total="grand_total",
		currency="currency",
		done="qty",
		per_received=None,
		per_billed="per_billed",
		kind=None,
	),
}


class NotSupportedInThisVersion(NotImplementedError):
	"""A part of the port that this version of the app does not provide (docs/KNOWN_LIMITATIONS.md)."""


def not_supported(what: str) -> NotSupportedInThisVersion:
	return NotSupportedInThisVersion(_("{0} is not supported in this version of AI Munimji.").format(what))


def to_date(value: Any) -> date | None:
	if not value:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return datetime.fromisoformat(str(value)[:19].replace(" ", "T")).date()


def chunks(seq: Sequence[str], n: int):
	for i in range(0, len(seq), n):
		yield list(seq[i : i + n])


def base_rate(line: dict, header: dict) -> float | None:
	"""The line's price in company currency: ERPNext's own base_rate, else rate x the order's conversion rate (a foreign price is never used as is)."""
	base = line.get("base_rate")
	if base:
		return float(base)
	rate = line.get("rate")
	return float(rate) * float(header.get("conversion_rate") or 1.0) if rate else None


def refused(error: str) -> PurchaseOrderResult:
	return PurchaseOrderResult(ok=False, error=error)


class FrappeERPClient:
	def __init__(self, *, system: bool = False, company: str | None = None) -> None:
		self.system = system
		if system:
			self._still_the_job()
		self.company = company or None
		self.voucher_types = list(CONSUMPTION_VOUCHERS)
		self.notes: list[
			str
		] = []  # what could not be read, for the call just made (the engine shows it instead of guessing)

	@staticmethod
	def _still_the_job() -> None:
		"""System mode is for the scheduled job and nobody else: it exists only while the session is Administrator (checked when it is made and before every read), and it never
		makes a document. It is what lets the job read the Tax Rules, which a Purchase User may not."""
		if frappe.session.user != "Administrator":
			raise frappe.PermissionError(
				_(
					"The system mode of the ERP client is only for the scheduled job, which runs as Administrator."
				)
			)

	# ------------------------------------------------------------------ low level: only permission-aware reads
	def _list(
		self,
		doctype: str,
		fields: list[Any],
		filters: list,
		order_by: str | None = None,
		parent: str | None = None,
		group_by: str | None = None,
	) -> list[dict]:
		# frappe.get_list also answers a person who has only the "select" right (the one that fills a link field's drop-down): on Item it returns item_name, item_group and the
		# other columns asked for. Reading a DocType's data needs the read right itself, so that is asked first; for a child table, the right on its parent.
		if self.system:
			self._still_the_job()
		needed = parent or doctype
		if not frappe.has_permission(
			needed, "read"
		):  # not throw=True: that pops a message up in the person's browser and raises an error with no text for the engine to show
			raise frappe.PermissionError(_("{0} may not read {1}.").format(frappe.session.user, needed))
		return frappe.get_list(
			doctype,
			fields=fields,
			filters=filters,
			order_by=order_by,
			parent_doctype=parent,
			group_by=group_by,
			limit_page_length=0,
		)

	def _optional(self, what: str, doctype: str, fields: list[Any], filters: list, **kw) -> list[dict] | None:
		"""A read whose result only refines the answer (a delivery record, a payment term): when the person may not read that DocType the figure is unknown (None), and the call says so."""
		try:
			return self._list(doctype, fields, filters, **kw)
		except frappe.PermissionError:
			self.notes.append(_("{0} could not be read: {1} is not open to this user.").format(what, doctype))
			return None

	def _doc(self, doctype: str, name: str):
		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
		return doc

	# ------------------------------------------------------------------ ERPClient
	def healthcheck(self) -> bool:
		"""True while the app is running on a site with a database and a signed-in person. There is no network hop to fail: if this code runs, the ERP is the site it runs on."""
		return bool(frappe.local.site) and frappe.local.db is not None and frappe.session.user != "Guest"

	# ------------------------------------------------------------------ StockERP
	def list_items(self) -> list[ItemInfo]:
		rows = self._list(
			"Item",
			["name", "item_name", "item_group", "stock_uom", "lead_time_days", "creation"],
			[["is_stock_item", "=", 1], ["disabled", "=", 0]],
		)
		first = self._first_movements()
		out = []
		for r in rows:
			starts = [d for d in (to_date(r.get("creation")), first.get(r["name"])) if d]
			out.append(
				ItemInfo(
					code=r["name"],
					name=r.get("item_name") or r["name"],
					group=r.get("item_group"),
					uom=r.get("stock_uom") or "units",
					lead_time_days=float(r["lead_time_days"]) if r.get("lead_time_days") else None,
					created=min(starts) if starts else None,
				)
			)
		return out

	def _first_movements(self) -> dict[str, date]:
		"""The day of each item's first stock ledger entry (an item's history starts there if that is earlier than its creation). Unknown, not guessed, if the ledger is closed to this user."""
		rows = self._optional(
			_("When each item's stock history begins"),
			"Stock Ledger Entry",
			["item_code", {"MIN": "posting_date", "as": "first_date"}],
			[["is_cancelled", "=", 0]],
			group_by="item_code",
		)
		return {
			r["item_code"]: d
			for r in rows or []
			if r.get("item_code") and (d := to_date(r.get("first_date")))
		}

	def list_warehouses(self) -> list[str]:
		rows = self._list("Warehouse", ["name", "is_group", "disabled"], [["disabled", "=", 0]])
		return sorted(r["name"] for r in rows if not r.get("is_group"))

	def get_stock(
		self, item_codes: Sequence[str], warehouses: Sequence[str] | None = None
	) -> dict[str, StockInfo]:
		wh = list(warehouses or [])
		bin_columns = [
			c
			for c in ("item_code", "warehouse", "actual_qty", *STOCK_COLUMNS, "projected_qty")
			if frappe.get_meta("Bin").has_field(c) or c in ("item_code", "warehouse")
		]
		totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
		projected: dict[str, float] = defaultdict(float)
		has_projected: set[str] = set()
		places: dict[str, list[WarehouseStock]] = defaultdict(list)
		transit = self._transit_warehouses()
		for chunk in chunks(item_codes, 100):
			filters: list = [["item_code", "in", chunk]]
			if wh:
				filters.append(["warehouse", "in", wh])
			for r in self._list("Bin", bin_columns, filters):
				code = r["item_code"]
				totals[code]["in_transit" if r.get("warehouse") in transit else "on_hand"] += float(
					r.get("actual_qty") or 0
				)
				for field, (_label, attr, _phrase) in STOCK_COLUMNS.items():
					totals[code][attr] += float(r.get(field) or 0)
				place = WarehouseStock(
					str(r.get("warehouse") or "(no warehouse)"),
					float(r.get("actual_qty") or 0),
					float(r.get("reserved_qty") or 0),
					float(r.get("ordered_qty") or 0),
					r.get("warehouse") in transit,
				)
				if place.on_hand or place.reserved or place.incoming:
					places[code].append(place)
				if r.get("projected_qty") is not None:
					projected[code] += float(r["projected_qty"])
					has_projected.add(code)
		on_order = [c for c in item_codes if totals.get(c, {}).get("incoming", 0) > 0]
		arrivals = self._next_arrivals(on_order, wh) if on_order else {}
		return {
			code: StockInfo(
				**dict(totals[code]),
				projected=projected[code] if code in has_projected else None,
				next_arrival=arrivals.get(code),
				by_warehouse=tuple(sorted(places[code], key=lambda p: (-p.on_hand, p.warehouse))),
			)
			if code in totals
			else StockInfo(on_hand=0.0)
			for code in item_codes
		}

	def _transit_warehouses(self) -> set[str]:
		rows = self._optional(
			_("Which warehouses are for stock in transit"),
			"Warehouse",
			["name", "is_group", "disabled"],
			[["warehouse_type", "=", "Transit"]],
		)
		return {r["name"] for r in rows or [] if not r.get("is_group") and not r.get("disabled")}

	def _next_arrivals(self, item_codes: Sequence[str], warehouses: Sequence[str]) -> dict[str, date]:
		"""Earliest expected receipt per item from open purchase orders. Unknown if the orders are closed to this user."""
		lines: list[dict] = []
		for chunk in chunks(item_codes, 100):
			filters: list = [["item_code", "in", chunk], ["docstatus", "=", 1]]
			if warehouses:
				filters.append(["warehouse", "in", list(warehouses)])
			got = self._optional(
				_("When an order on its way is due"),
				"Purchase Order Item",
				["parent", "item_code", "qty", "received_qty", "schedule_date"],
				filters,
				order_by="schedule_date asc",
				parent="Purchase Order",
			)
			if got is None:
				return {}
			lines += got
		lines = [
			r
			for r in lines
			if r.get("schedule_date") and float(r.get("qty") or 0) - float(r.get("received_qty") or 0) > 0
		]
		receiving: set[str] = set()
		for chunk in chunks(sorted({r["parent"] for r in lines}), 100):
			receiving.update(
				r["name"]
				for r in self._list(
					"Purchase Order",
					["name", "status"],
					[["name", "in", chunk], ["status", "in", ["To Receive and Bill", "To Receive"]]],
				)
			)
		out: dict[str, date] = {}
		for r in lines:
			d = to_date(r["schedule_date"])
			if (
				r["parent"] in receiving
				and d is not None
				and (r["item_code"] not in out or d < out[r["item_code"]])
			):
				out[r["item_code"]] = d
		return out

	def get_consumption(
		self, item_codes: Sequence[str], start: date, end: date, warehouses: Sequence[str] | None = None
	) -> dict[str, list[DailyUsage]]:
		per_day: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
		for chunk in chunks(item_codes, 50):
			filters: list = [
				["item_code", "in", chunk],
				["actual_qty", "<", 0],
				["is_cancelled", "=", 0],
				["posting_date", ">=", start.isoformat()],
				["posting_date", "<=", end.isoformat()],
				["voucher_type", "in", self.voucher_types],
			]
			if warehouses:
				filters.append(["warehouse", "in", list(warehouses)])
			for r in self._list(
				"Stock Ledger Entry",
				["item_code", "posting_date", "actual_qty"],
				filters,
				order_by="posting_date asc",
			):
				d = to_date(r["posting_date"])
				if d is not None:
					per_day[r["item_code"]][d] += -float(r["actual_qty"])
		return {code: [DailyUsage(d, q) for d, q in sorted(days.items())] for code, days in per_day.items()}

	# ------------------------------------------------------------------ PurchasingERP: vendors
	def get_vendor_offers(
		self, item_code: str, since: date, quotes: QuoteRule | None = None
	) -> list[VendorOffer]:
		"""Suppliers for one item, from its supplier list and its submitted purchase orders (and, with `quotes`, their valid quotations). The order lines are required: a person who may
		not read purchase orders gets `frappe.PermissionError`. The delivery record, payment terms, country and quotations only refine the answer: closed to this user, they are unknown."""
		lines = self._list(
			"Purchase Order Item",
			["parent", "qty", "rate", "base_rate", "schedule_date"],
			[["item_code", "=", item_code], ["docstatus", "=", 1]],
			parent="Purchase Order",
		)
		listed_rows = self._optional(
			_("The item's supplier list"),
			"Item Supplier",
			["supplier"],
			[["parent", "=", item_code]],
			parent="Item",
		)
		listed = {r["supplier"] for r in listed_rows or [] if r.get("supplier")}
		headers: dict[str, dict] = {}
		for chunk in chunks(sorted({r["parent"] for r in lines}), 100):
			for h in self._list(
				"Purchase Order",
				["name", "supplier", "supplier_name", "transaction_date", "currency", "conversion_rate"],
				[["name", "in", chunk], ["docstatus", "=", 1], ["transaction_date", ">=", since.isoformat()]],
			):
				headers[h["name"]] = h

		receipts = self._first_receipts(item_code, sorted(headers))
		by_supplier: dict[str, list[tuple[date, dict, dict]]] = defaultdict(list)
		for line in lines:
			h = headers.get(line["parent"])
			d = to_date(h.get("transaction_date")) if h else None
			if h and d and h.get("supplier"):
				by_supplier[h["supplier"]].append((d, line, h))

		quoted = self._quotations(item_code, quotes) if quotes is not None else {}
		suppliers = sorted(set(by_supplier) | listed | set(quoted))
		info: dict[str, dict] = {}
		terms_days: dict[str, float] = {}
		for chunk in chunks(suppliers, 100):
			for s in (
				self._optional(
					_("Supplier details"),
					"Supplier",
					["name", "supplier_name", "payment_terms", "disabled", "country"],
					[["name", "in", chunk]],
				)
				or []
			):
				info[s["name"]] = s
		templates = sorted({s["payment_terms"] for s in info.values() if s.get("payment_terms")})
		for chunk in chunks(templates, 100):
			for t in (
				self._optional(
					_("Payment terms"),
					"Payment Terms Template Detail",
					["parent", "credit_days"],
					[["parent", "in", chunk]],
					parent="Payment Terms Template",
				)
				or []
			):
				terms_days[t["parent"]] = max(
					terms_days.get(t["parent"], 0.0), float(t.get("credit_days") or 0)
				)

		offers: list[VendorOffer] = []
		for code in suppliers:
			if info.get(code, {}).get("disabled"):
				continue
			history = sorted(by_supplier.get(code, []), key=lambda t: t[0])
			rates = [r for r in (base_rate(line, h) for _d, line, h in history) if r]
			leads, on_time = [], []
			for order_date, line, h in history:
				got = receipts.get(h["name"])
				if got is None:
					continue
				leads.append(float((got - order_date).days))
				promised = to_date(line.get("schedule_date"))
				if promised is not None:
					on_time.append(1.0 if got <= promised else 0.0)
			template = info.get(code, {}).get("payment_terms")
			qt = quoted.get(code)
			offers.append(
				VendorOffer(
					supplier=code,
					name=info.get(code, {}).get("supplier_name")
					or (history[-1][2].get("supplier_name") if history else None)
					or (qt or {}).get("supplier_name")
					or code,
					unit_price=base_rate(history[-1][1], history[-1][2]) if history else None,
					avg_price=sum(rates) / len(rates) if rates else None,
					lead_time_days=sum(leads) / len(leads) if leads else None,
					on_time_rate=sum(on_time) / len(on_time) if on_time else None,
					orders=len(history),
					last_order=history[-1][0] if history else None,
					payment_days=terms_days.get(template) if template else None,
					listed=code in listed,
					currency=(history[-1][2].get("currency") if history else None)
					or (qt or {}).get("currency"),
					country=info.get(code, {}).get("country"),
					quote_price=(qt or {}).get("price"),
					quote_ref=(qt or {}).get("name"),
					quote_date=(qt or {}).get("date"),
					quote_valid_till=(qt or {}).get("valid_till"),
					quote_qty=(qt or {}).get("qty"),
					quote_lead_days=(qt or {}).get("lead_days"),
				)
			)
		return offers

	def _first_receipts(self, item_code: str, order_names: list[str]) -> dict[str, date]:
		"""Purchase order -> the date of its first goods receipt for this item. Unknown (empty) if receipts are closed to this user.

		A return (a Purchase Receipt with is_return = 1: goods sent back, with a negative quantity and the same purchase order) is not a delivery and is left out: it is neither the first
		receipt of an order nor a late one. The Purchase Order itself has no is_return field in v16 (checked on 16.55.2), so the order history is not filtered, and nothing in the app reads a
		Purchase Invoice."""
		receipts: dict[str, date] = {}
		for chunk in chunks(order_names, 100):
			items = self._optional(
				_("The delivery record"),
				"Purchase Receipt Item",
				["parent", "purchase_order"],
				[["item_code", "=", item_code], ["docstatus", "=", 1], ["purchase_order", "in", chunk]],
				parent="Purchase Receipt",
			)
			if items is None:
				return {}
			prs = {r["parent"]: r["purchase_order"] for r in items if r.get("purchase_order")}
			for chunk2 in chunks(sorted(prs), 100):
				for pr in self._list(
					"Purchase Receipt",
					["name", "posting_date"],
					[["name", "in", chunk2], ["docstatus", "=", 1], ["is_return", "=", 0]],
				):
					d, po = to_date(pr.get("posting_date")), prs[pr["name"]]
					if d is not None and (po not in receipts or d < receipts[po]):
						receipts[po] = d
		return receipts

	def _quotations(self, item_code: str, rule: QuoteRule) -> dict[str, dict[str, Any]]:
		"""Each supplier's latest VALID supplier quotation for this item (submitted, not stopped or expired, in date or, with no end date, not older than the rule allows). What
		cannot be read means 'no quotation', never a guess."""
		lines = self._optional(
			_("Supplier quotations"),
			"Supplier Quotation Item",
			["parent", "qty", "rate", "base_rate", "lead_time_days"],
			[["item_code", "=", item_code], ["docstatus", "=", 1]],
			parent="Supplier Quotation",
		)
		if not lines:
			return {}
		heads: dict[str, dict] = {}
		for chunk in chunks(sorted({r["parent"] for r in lines}), 100):
			for h in self._list(
				"Supplier Quotation",
				[
					"name",
					"supplier",
					"supplier_name",
					"transaction_date",
					"valid_till",
					"currency",
					"conversion_rate",
					"status",
				],
				[["name", "in", chunk], ["docstatus", "=", 1]],
			):
				heads[h["name"]] = h
		best: dict[str, dict[str, Any]] = {}
		for line in lines:
			h = heads.get(line["parent"])
			if (
				not h
				or not h.get("supplier")
				or (h.get("status") or "Submitted") in ("Expired", "Stopped", "Cancelled", "Draft")
			):
				continue
			made, until = to_date(h.get("transaction_date")), to_date(h.get("valid_till"))
			if until is not None:
				if until < rule.today:
					continue
			elif made is None or (rule.today - made).days > rule.max_age_days:
				continue
			price = base_rate(line, h)
			if not price:
				continue
			cand = {"name": h["name"], "price": price, "date": made, "valid_till": until, "qty": float(line.get("qty") or 0) or None, "currency": h.get("currency"),
			        "lead_days": float(line["lead_time_days"]) if line.get("lead_time_days") else None, "supplier_name": h.get("supplier_name")}  # fmt: skip
			cur = best.get(h["supplier"])
			if (
				cur is None
				or (made or date.min, h["name"]) > (cur["date"] or date.min, cur["name"])
				or (cand["name"] == cur["name"] and price < cur["price"])
			):
				best[h["supplier"]] = cand
		return best

	def item_min_order_qty(self, item_code: str) -> float | None:
		rows = self._list("Item", ["min_order_qty"], [["name", "=", item_code]])
		moq = rows[0].get("min_order_qty") if rows else None
		return float(moq) if moq else None

	# ------------------------------------------------------------------ PurchasingERP: taxes
	def get_purchase_taxes(self, supplier: str, item_code: str, posting_date: date) -> TaxSetup:
		"""The duties and taxes ERPNext would put on a purchase of this item from this supplier: the Tax Rule's template, else the company's default one, with the item's own tax
		template adjusting the rates. Reading Tax Rules needs Accounts Manager; a person without it gets `frappe.PermissionError` (the job, as Administrator, reads them and keeps the
		figures with the proposal). Whatever cannot be read is returned as a note, never filled in."""
		notes: list[str] = []
		sup = next(
			iter(
				self._list(
					"Supplier",
					["name", "supplier_group", "tax_category", "country"],
					[["name", "=", supplier]],
				)
			),
			{},
		)
		tax_category = sup.get("tax_category") or None
		company = self._company()
		template = self._tax_rule_template(
			supplier, sup.get("supplier_group"), tax_category, company, posting_date, notes
		)
		source = "tax rule" if template else "none"
		if not template:
			flt: list = [["is_default", "=", 1], ["disabled", "=", 0]] + (
				[["company", "=", company]] if company else []
			)
			defaults = self._list("Purchase Taxes and Charges Template", ["name", "company"], flt)
			if len(defaults) == 1:
				template, source = defaults[0]["name"], "default template"
			elif len(defaults) > 1:
				notes.append("several companies have a default purchase taxes template and no company is set")
			else:
				notes.append("there is no default purchase taxes template")
		if not template:
			return TaxSetup(None, "none", (), tuple(notes), tax_category)
		doc = self._doc("Purchase Taxes and Charges Template", template)
		rows = [r.as_dict() for r in doc.get("taxes")]
		if any(r.get("included_in_print_rate") for r in rows):
			notes.append(
				"some template rows are included in the price; this agent treats vendor prices as excluding tax"
			)
		item_template, overrides = self._item_tax_overrides(item_code, tax_category, posting_date, notes)
		out: list[TaxRow] = []
		for r in rows:
			rate, from_item = float(r.get("rate") or 0), False
			account = r.get("account_head") or ""
			if account in overrides and r.get("charge_type") in (
				"On Net Total",
				"On Previous Row Amount",
				"On Previous Row Total",
				"On Item Quantity",
			):
				rate, from_item = overrides[account], True
			out.append(TaxRow(description=r.get("description") or account, charge_type=r.get("charge_type") or "", rate=rate, amount=float(r.get("tax_amount") or 0), category=r.get("category") or "Total",
			                  add_deduct=r.get("add_deduct_tax") or "Add", row_id=int(r["row_id"]) if r.get("row_id") else None, account=account, rate_from_item_template=from_item))  # fmt: skip
		return TaxSetup(template, source, tuple(out), tuple(notes), tax_category, item_template)

	def _tax_rule_template(
		self,
		supplier: str,
		supplier_group: str | None,
		tax_category: str | None,
		company: str | None,
		posting_date: date,
		notes: list[str],
	) -> str | None:
		"""ERPNext's own Tax Rule selection for a purchase (same logic as its `get_tax_template`): a rule must be in date, have exactly the supplier's tax category, and each of
		supplier / supplier group / company blank or equal; the rule that sets the most of those wins, then the higher priority. Rules that depend on addresses or items are skipped
		and reported."""
		fields = [
			"name",
			"tax_type",
			"purchase_tax_template",
			"supplier",
			"supplier_group",
			"tax_category",
			"company",
			"priority",
			"from_date",
			"to_date",
			*UNJUDGEABLE_RULE_FIELDS,
		]
		candidates, skipped = [], []
		for r in self._list("Tax Rule", fields, [["tax_type", "=", "Purchase"]]):
			tpl = r.get("purchase_tax_template")
			f, t = to_date(r.get("from_date")), to_date(r.get("to_date"))
			if not tpl or (f and f > posting_date) or (t and t < posting_date):
				continue
			if (r.get("tax_category") or "") != (tax_category or ""):
				continue
			if (r.get("supplier") or supplier) != supplier or (
				r.get("supplier_group") or supplier_group or ""
			) != (supplier_group or ""):
				continue
			if r.get("company") and r["company"] != company:
				if not company:
					skipped.append(f"{r['name']} (for company {r['company']}, but no company is set)")
				continue
			if any(r.get(k) for k in UNJUDGEABLE_RULE_FIELDS):
				skipped.append(f"{r['name']} (depends on addresses or items)")
				continue
			matched = sum(1 for k in ("supplier", "supplier_group", "company") if r.get(k)) + 1
			candidates.append((matched, int(r.get("priority") or 0), r["name"], tpl))
		if skipped:
			notes.append(
				"Tax Rules not considered because they cannot be judged from here: " + "; ".join(skipped)
			)
		if not candidates:
			notes.append("no Tax Rule matched this vendor")
			return None
		candidates.sort()
		best = candidates[-1]
		tied = {c[3] for c in candidates if c[:2] == best[:2]}
		if len(tied) > 1:
			notes.append(
				f"several Tax Rules tie for this vendor ({', '.join(sorted(tied))}); template '{best[3]}' was used"
			)
		return best[3]

	def _item_tax_overrides(
		self, item_code: str, tax_category: str | None, posting_date: date, notes: list[str]
	) -> tuple[str | None, dict[str, float]]:
		"""The item's own tax template (if one fits the supplier's tax category and date): {account: rate}, 0 where not applicable."""
		try:
			item = self._doc("Item", item_code)
			fits = []
			for t in item.get("taxes") or []:
				valid_from = to_date(t.get("valid_from"))
				if (
					t.get("item_tax_template")
					and (not t.get("tax_category") or t.get("tax_category") == tax_category)
					and (not valid_from or valid_from <= posting_date)
				):
					fits.append(
						(1 if t.get("tax_category") else 0, valid_from or date.min, t["item_tax_template"])
					)
			if not fits:
				return None, {}
			name = max(fits, key=lambda f: (f[0], f[1]))[2]
			tpl = self._doc("Item Tax Template", name)
			return name, {
				d.tax_type: (0.0 if d.get("not_applicable") else float(d.get("tax_rate") or 0))
				for d in tpl.get("taxes") or []
				if d.get("tax_type")
			}
		except frappe.PermissionError:
			notes.append("could not read the item's tax template: it is not open to this user")
			return None, {}

	# ------------------------------------------------------------------ PurchasingERP: documents already made
	def get_documents(
		self,
		doctype: str,
		name: str | None = None,
		item_code: str | None = None,
		since: date | None = None,
		limit: int = 20,
		open_only: bool = False,
	) -> list[dict[str, Any]]:
		spec = DOC_SPECS.get(doctype)
		if spec is None:
			raise not_supported(_("Reading {0}").format(doctype))
		flt: list = [["docstatus", "<", 3]]
		if open_only:
			flt.append(["status", "not in", FINISHED])
		if name:
			flt.append(["name", "=", name])
		if since:
			flt.append([spec["date"], ">=", since.isoformat()])
		if item_code:
			parents = sorted(
				{
					r["parent"]
					for r in self._list(
						spec["child"], ["parent"], [["item_code", "=", item_code]], parent=doctype
					)
				}
			)
			if not parents:
				return []
			flt.append(["name", "in", parents[:500]])
		base = ["name", "status", "docstatus", "owner", "creation", APPROVED_BY] + [
			spec[k]
			for k in (
				"party",
				"party_id",
				"date",
				"due",
				"total",
				"currency",
				"per_received",
				"per_billed",
				"kind",
			)
			if spec[k]
		]
		rows = self._list(doctype, base, flt, order_by="creation desc")[:limit]
		lines_by: dict[str, list[dict]] = defaultdict(list)
		for chunk in chunks([r["name"] for r in rows], 100):
			for ln in self._list(
				spec["child"],
				["parent", "item_code", "item_name", "qty", "uom", spec["done"]],
				[["parent", "in", chunk]],
				parent=doctype,
			):
				lines_by[ln["parent"]].append({"item_code": ln.get("item_code"), "item_name": ln.get("item_name"), "qty": float(ln.get("qty") or 0), "uom": ln.get("uom"), "done_qty": float(ln.get(spec["done"]) or 0)})  # fmt: skip
		return [
			{
				"doctype": doctype,
				"name": r["name"],
				"status": r.get("status") or "",
				"docstatus": int(r.get("docstatus") or 0),
				"party": r.get(spec["party"]) if spec["party"] else None,
				"party_id": r.get(spec["party_id"]) if spec["party_id"] else None,
				"date": r.get(spec["date"]),
				"due": r.get(spec["due"]) if spec["due"] else None,
				"created_by": r.get("owner"),
				"approved_by": r.get(APPROVED_BY) or "",
				"per_received": float(r.get(spec["per_received"]) or 0) if spec["per_received"] else None,
				"per_billed": float(r.get(spec["per_billed"]) or 0) if spec["per_billed"] else None,
				"total": float(r.get(spec["total"]) or 0) if spec["total"] else None,
				"currency": r.get(spec["currency"]) if spec["currency"] else None,
				"kind": r.get(spec["kind"]) if spec["kind"] else None,
				"lines": lines_by.get(r["name"], []),
			}
			for r in rows
		]

	def find_by_reference(self, doctype: str, reference: str) -> FoundDocument | None:
		"""The not-cancelled document of this type made for `reference`, or None. Raises if the person may not read that DocType (it cannot be asked).
		No reference means nothing to look for: Frappe reads an empty filter value as 'is empty', which would match every document that was made by hand."""
		if not str(reference or "").strip():
			return None
		rows = self._list(
			doctype,
			["name", APPROVED_BY],
			[[REF, "=", reference], ["docstatus", "<", 2]],
			order_by="creation desc",
		)
		return FoundDocument(doctype, rows[0]["name"], str(rows[0].get(APPROVED_BY) or "")) if rows else None

	# ------------------------------------------------------------------ PurchasingERP: making drafts
	def _acting_is_me(self, acting: Any) -> PurchaseOrderResult | None:
		"""Every write starts here. This client always acts as the signed-in user: a caller that passes someone else's session is refused, not obeyed as if it were someone else.
		In system mode (the scheduled job) nothing is written at all: the job reads and proposes, and a document is made only as the person who approved it."""
		if self.system:
			return refused(
				_(
					"The scheduled job reads and proposes; a document is made only as the person who approved it."
				)
			)
		if acting is not None and getattr(acting, "user", frappe.session.user) != frappe.session.user:
			return refused(
				_("This client makes documents as the person signed in, {0}; it cannot act for {1}.").format(
					frappe.session.user, acting.user
				)
			)
		return None

	def _company(self) -> str | None:
		"""The company for a new document: the one given, else the user's or the site's default, else the only company. None if there is none or several and no default."""
		if self.company:
			return self.company
		default = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
		if default:
			return default
		names = [r["name"] for r in self._list("Company", ["name"], [])]
		return names[0] if len(names) == 1 else None

	def _hold(self, doctype: str, reference: str) -> None:
		"""Take the row lock for making documents of this type: held until the transaction ends, on every worker and server that shares the database (stores/locks.py). Nothing when
		there is no reference to serialise on. The one place the lock is taken, so that a test can take it away."""
		if reference:
			locks.take(doctype)

	def _already_made(self, doctype: str, reference: str) -> str | None:
		"""The not-cancelled document this reference has already led to, found with a locking read (a plain read may not see what another connection committed after this one began),
		then checked against what this person may read: someone who may not read these documents cannot know whether one exists, so nothing is made for them."""
		name = locks.find_locked(doctype, {REF: reference, "docstatus": ["<", 2]})
		if name is None:
			return None
		frappe.get_doc(doctype, name, for_update=True).check_permission(
			"read"
		)  # a locking read again: a plain one may not see a document that was committed a moment ago
		return name

	def _make(
		self, doctype: str, body: dict[str, Any], reference: str, approved_by: str, label: str, acting: Any
	) -> PurchaseOrderResult:
		"""Insert a DRAFT as the signed-in person. Under a row lock named for the reference, an earlier not-cancelled document of the same reference is returned instead of making
		a second one: two presses of one button, or a retry, give one document, whichever worker or server they reach. Never submitted."""
		other = self._acting_is_me(acting)
		if other is not None:
			return other
		company = self._company()
		if not company:
			return refused(
				_(
					"There are several companies and no default company is set, so nothing was created: it would land in whichever company the signed-in user has."
				)
			)
		body = {"doctype": doctype, "company": company, **body}
		reference = str(reference or "").strip()
		try:
			self._hold(doctype, reference)
			if reference:
				existing = self._already_made(doctype, reference)
				if existing is not None:
					return PurchaseOrderResult(ok=True, name=existing)
				body[REF] = reference
			if approved_by:
				body[APPROVED_BY] = approved_by[:140]
			doc = frappe.get_doc(body)
			if hasattr(doc, "set_missing_values"):
				doc.set_missing_values()
			doc.insert()
			return PurchaseOrderResult(ok=True, name=doc.name)
		except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
			return refused(
				_(
					"Another press for this request is still being handled. Wait a moment and look at the {0} before pressing again."
				).format(label)
			)
		except frappe.PermissionError as exc:
			return refused(_("{0} may not create a {1}: {2}").format(frappe.session.user, label, _plain(exc)))
		except frappe.ValidationError as exc:
			return refused(_("The {0} was refused: {1}").format(label, _plain(exc)))
		except Exception as exc:
			return refused(_("The {0} could not be made: {1}").format(label, _plain(exc)))

	def create_purchase_order(
		self, draft: PurchaseOrderDraft, acting: Any | None = None
	) -> PurchaseOrderResult:
		line: dict[str, Any] = {
			"item_code": draft.item_code,
			"qty": draft.qty,
			"rate": draft.rate,
			"uom": draft.uom,
			"schedule_date": draft.required_by.isoformat(),
		}
		body: dict[str, Any] = {
			"supplier": draft.supplier,
			"transaction_date": date.today().isoformat(),
			"schedule_date": draft.required_by.isoformat(),
			"items": [line],
		}
		try:
			self._in_supplier_currency(body, draft)
		except (frappe.PermissionError, frappe.ValidationError) as exc:
			return refused(
				_("Nothing was created: the supplier's currency could not be worked out ({0}).").format(
					_plain(exc)
				)
			)
		if draft.supplier_quotation:
			self._link_quotation(body, draft)
		if draft.vendor_note:
			body["terms"] = draft.vendor_note
		if draft.taxes_template:
			body["taxes_and_charges"] = draft.taxes_template
			self._apply_taxes(body, draft)
		return self._make(
			"Purchase Order", body, draft.reference, draft.approved_by, _("purchase order"), acting
		)

	def create_material_request(
		self, draft: RequisitionDraft, acting: Any | None = None
	) -> PurchaseOrderResult:
		line: dict[str, Any] = {
			"item_code": draft.item_code,
			"qty": draft.qty,
			"uom": draft.uom,
			"schedule_date": draft.required_by.isoformat(),
		}
		if draft.rate:
			line["rate"] = draft.rate
		body: dict[str, Any] = {
			"material_request_type": "Purchase",
			"transaction_date": date.today().isoformat(),
			"schedule_date": draft.required_by.isoformat(),
			"items": [line],
		}
		if draft.note and draft.reference:
			body[NOTE] = draft.note[:900]
		return self._make(
			"Material Request", body, draft.reference, draft.approved_by, _("purchase requisition"), acting
		)

	def create_stock_transfer(
		self, draft: StockTransferDraft, acting: Any | None = None
	) -> PurchaseOrderResult:
		if draft.from_warehouse == draft.to_warehouse:
			return refused(_("The two warehouses are the same."))
		line = {"item_code": draft.item_code, "qty": draft.qty, "uom": draft.uom, "stock_uom": draft.uom, "conversion_factor": 1, "transfer_qty": draft.qty, "s_warehouse": draft.from_warehouse, "t_warehouse": draft.to_warehouse}  # fmt: skip
		body: dict[str, Any] = {"stock_entry_type": "Material Transfer", "purpose": "Material Transfer", "posting_date": date.today().isoformat(), "posting_time": nowtime(), "from_warehouse": draft.from_warehouse, "to_warehouse": draft.to_warehouse, "items": [line]}  # fmt: skip
		if draft.remarks:
			body["remarks"] = draft.remarks[:900]
		return self._make(
			"Stock Entry", body, draft.reference, draft.approved_by, _("stock transfer"), acting
		)

	def _company_currency(self) -> str:
		company = self._company()
		rows = self._list("Company", ["default_currency"], [["name", "=", company]]) if company else []
		return (rows[0].get("default_currency") if rows else "") or ""

	def _in_supplier_currency(self, body: dict[str, Any], draft: PurchaseOrderDraft) -> None:
		"""Vendor prices are compared and stored in company currency; a supplier billing in another currency needs the order in THAT currency, at the latest exchange rate."""
		company_ccy = self._company_currency()
		if not company_ccy:
			return
		rows = self._list("Supplier", ["default_currency"], [["name", "=", draft.supplier]])
		sup_ccy = (rows[0].get("default_currency") if rows else None) or company_ccy
		if sup_ccy == company_ccy:
			return
		rates = self._list(
			"Currency Exchange",
			["exchange_rate", "date"],
			[
				["from_currency", "=", sup_ccy],
				["to_currency", "=", company_ccy],
				["date", "<=", date.today().isoformat()],
			],
			order_by="date desc",
		)
		if not rates:
			raise frappe.ValidationError(
				_("no exchange rate from {0} to {1} is set up").format(sup_ccy, company_ccy)
			)
		rate = float(rates[0]["exchange_rate"])
		body["currency"], body["conversion_rate"] = sup_ccy, rate
		for line in body["items"]:
			line["rate"] = round(float(line["rate"]) / rate, 4)

	def _link_quotation(self, body: dict[str, Any], draft: PurchaseOrderDraft) -> None:
		"""Tie the order's item to the Supplier Quotation its price came from when ERPNext would accept the link (submitted, same supplier and currency); otherwise leave it out."""
		try:
			sq = self._doc("Supplier Quotation", draft.supplier_quotation)
		except (frappe.PermissionError, frappe.DoesNotExistError):
			return
		currency = body.get("currency") or self._company_currency()
		lines = [
			r
			for r in sq.get("items") or []
			if r.get("item_code") == draft.item_code and float(r.get("rate") or 0) > 0
		]
		if not (sq.docstatus == 1 and sq.supplier == draft.supplier and sq.currency == currency and lines):
			return
		line = min(lines, key=lambda r: float(r.get("base_rate") or r.get("rate") or 0))
		item = body["items"][0]
		item["supplier_quotation"] = draft.supplier_quotation
		item["supplier_quotation_item"] = line.name
		item["rate"] = float(line.rate)

	def _apply_taxes(self, body: dict[str, Any], draft: PurchaseOrderDraft) -> None:
		"""Put the template's rows on the order, and the item's own tax template on its line: naming the template is not enough for a document made without the form. Best effort."""
		try:
			tpl = self._doc("Purchase Taxes and Charges Template", draft.taxes_template)
			rate = float(body.get("conversion_rate") or 1.0) or 1.0
			rows = []
			for r in tpl.get("taxes"):
				row = {"charge_type": r.charge_type, "account_head": r.account_head, "description": r.description or r.account_head, "rate": r.rate or 0, "category": r.category or "Total", "add_deduct_tax": r.add_deduct_tax or "Add"}  # fmt: skip
				for key in ("row_id", "cost_center", "included_in_print_rate"):
					if r.get(key):
						row[key] = r.get(key)
				if r.charge_type == "Actual":
					row["tax_amount"] = round(float(r.tax_amount or 0) / rate, 2)
				rows.append(row)
			if rows:
				body["taxes"] = rows
			sup = self._list("Supplier", ["tax_category"], [["name", "=", draft.supplier]])
			name, overrides = self._item_tax_overrides(
				draft.item_code, (sup[0].get("tax_category") if sup else None) or None, date.today(), []
			)
			if name:
				body["items"][0]["item_tax_template"] = name
				body["items"][0]["item_tax_rate"] = json.dumps(overrides)
		except frappe.PermissionError:
			pass  # the order is still made with the template named; the tax table can be filled in by choosing the template again

	# ------------------------------------------------------------------ PurchasingERP: changing and cancelling what this application made
	def _own_order(self, name: str, reference: str) -> tuple[Any | None, PurchaseOrderResult | None]:
		"""The order, if it exists, carries this request's reference (or one that starts with it and a dash), and the person may read it. (doc, None) or (None, the result to return)."""
		try:
			visible = self._list("Purchase Order", ["name"], [["name", "=", name]])
		except frappe.PermissionError as exc:
			return None, refused(
				_("{0} may not see purchase orders ({1}).").format(frappe.session.user, _plain(exc))
			)
		if not visible:
			return None, PurchaseOrderResult(ok=True, name=name, note="already gone")
		doc = frappe.get_doc("Purchase Order", name)
		doc.check_permission("read")
		found = str(doc.get(REF) or "")
		if not reference or not (found == reference or found.startswith(reference + "-")):
			return None, refused(_("It was not created by AI Munimji for this request, so it is left alone."))
		return doc, None

	def update_purchase_order_qty(
		self, name: str, reference: str, item_code: str, qty: float, acting: Any | None = None
	) -> PurchaseOrderResult:
		other = self._acting_is_me(acting)
		if other is not None:
			return other
		doc, result = self._own_order(name, reference)
		if result is not None:
			return refused(_("It is no longer there.")) if result.ok else result
		if doc.docstatus == 2:
			return refused(_("It has been cancelled."))
		if doc.status in ("Closed", "Completed", "On Hold", "Delivered"):
			return refused(_("It is {0}; reopen it first.").format(doc.status))
		rows = [r for r in doc.get("items") if r.item_code == item_code]
		if len(rows) != 1:
			return refused(
				_("It has {0} lines for {1}, so change it in the form.").format(len(rows), item_code)
			)
		row = rows[0]
		if qty < float(row.received_qty or 0):
			return refused(
				_("{0} have already been received against it, so it cannot be for less than that.").format(
					f"{float(row.received_qty):g}"
				)
			)
		if float(row.billed_amt or 0) > 0 and qty * float(row.rate or 0) < float(row.billed_amt) - 0.005:
			return refused(
				_("{0} has already been invoiced against it, so it cannot be for less than that.").format(
					f"{float(row.billed_amt):,.2f}"
				)
			)
		try:
			if doc.docstatus == 0:
				doc.check_permission("write")
				row.qty = qty
				doc.save()
			else:
				from erpnext.controllers.accounts_controller import update_child_qty_rate

				# "Update Items" deletes every line that is not listed and blanks a description sent without one: every line is sent as it is, only ours changes its quantity
				trans = [{"docname": r.name, "item_code": r.item_code, "qty": qty if r.name == row.name else r.qty, "rate": r.rate, "conversion_factor": r.conversion_factor or 1, "uom": r.uom,
				          "schedule_date": str(r.schedule_date) if r.schedule_date else None, "description": r.description} for r in doc.get("items")]  # fmt: skip
				update_child_qty_rate("Purchase Order", json.dumps(trans), doc.name, "items")
		except frappe.PermissionError as exc:
			return refused(
				_("{0} may not change a purchase order: {1}").format(frappe.session.user, _plain(exc))
			)
		except frappe.ValidationError as exc:
			return refused(_("The change was refused: {0}").format(_plain(exc)))
		total = frappe.get_list(
			"Purchase Order", fields=["grand_total"], filters=[["name", "=", name]], limit_page_length=1
		)
		return PurchaseOrderResult(
			ok=True,
			name=name,
			total=float(total[0]["grand_total"]) if total else None,
			submitted=doc.docstatus == 1,
			note="changed the quantity",
		)

	def cancel_purchase_order(
		self, name: str, reference: str, acting: Any | None = None
	) -> PurchaseOrderResult:
		other = self._acting_is_me(acting)
		if other is not None:
			return other
		doc, result = self._own_order(name, reference)
		if result is not None:
			return result
		if doc.docstatus == 2:
			return PurchaseOrderResult(ok=True, name=name, note="already cancelled")
		got, billed = float(doc.per_received or 0), float(doc.per_billed or 0)
		if got > 0 or billed > 0:
			return refused(
				_(
					"{0}% of it has been received and {1}% billed, so it has to be dealt with in ERPNext (cancel the receipt or invoice first)."
				).format(f"{got:g}", f"{billed:g}")
			)
		verb = "delete" if doc.docstatus == 0 else "cancel"
		try:
			if doc.docstatus == 0:
				frappe.delete_doc("Purchase Order", name)  # checks the person's Delete right
			else:
				doc.check_permission("cancel")
				doc.cancel()
		except frappe.PermissionError as exc:
			return refused(
				_("{0} may not {1} a purchase order: {2}").format(frappe.session.user, verb, _plain(exc))
			)
		except frappe.ValidationError as exc:
			return refused(
				_("It could not be {0}: {1}").format(
					_("deleted") if verb == "delete" else _("cancelled"), _plain(exc)
				)
			)
		return PurchaseOrderResult(
			ok=True, name=name, note="deleted the draft" if verb == "delete" else "cancelled it"
		)

	# ------------------------------------------------------------------ FollowUpERP: the one read the stock analysis uses
	def get_open_sales_orders(self, item_codes: Sequence[str], until: date) -> dict[str, list[SalesDue]]:
		"""Quantity still to deliver on submitted, open sales orders due by `until` (overdue lines included), in the stock unit. No customer is read."""
		out: dict[str, list[SalesDue]] = defaultdict(list)
		lines: list[dict] = []
		for chunk in chunks(list(item_codes), 100):
			lines += self._list(
				"Sales Order Item",
				["parent", "item_code", "qty", "delivered_qty", "conversion_factor", "delivery_date"],
				[
					["item_code", "in", chunk],
					["docstatus", "=", 1],
					["delivery_date", "<=", until.isoformat()],
				],
				parent="Sales Order",
			)
		open_orders: set[str] = set()
		for chunk in chunks(sorted({r["parent"] for r in lines}), 100):
			for h in self._list(
				"Sales Order", ["name", "status"], [["name", "in", chunk], ["docstatus", "=", 1]]
			):
				if (h.get("status") or "") not in ("Closed", "Completed", "Cancelled", "On Hold", "To Bill"):
					open_orders.add(h["name"])
		for r in lines:
			left = (float(r.get("qty") or 0) - float(r.get("delivered_qty") or 0)) * float(
				r.get("conversion_factor") or 1
			)
			if r["parent"] in open_orders and left > 0 and r.get("item_code"):
				out[r["item_code"]].append(SalesDue(r["item_code"], to_date(r.get("delivery_date")), left))
		return dict(out)

	# ------------------------------------------------------------------ left out of this version (docs/KNOWN_LIMITATIONS.md)
	def get_receipt_lines(self, since: date):
		raise not_supported(_("Reading goods receipts for the delivery and invoice checks"))

	def get_stock_counts(self, since: date):
		raise not_supported(_("Reading stock counts"))

	def get_stock_values(self, item_codes: Sequence[str]):
		raise not_supported(_("Reading the value of stock"))

	def last_purchase_dates(self, item_codes: Sequence[str]):
		raise not_supported(_("Reading when each item was last bought"))

	def get_item_alternatives(self, item_code: str):
		raise not_supported(_("Reading item alternatives"))

	def get_supplier_contact(self, supplier: str):
		raise not_supported(_("Reading a supplier's contact details"))

	def send_email(
		self, recipients: Sequence[str], subject: str, body: str, reference_doctype: str, reference_name: str
	):
		raise not_supported(_("Sending e-mail"))


def _plain(exc: BaseException) -> str:
	"""A Frappe error in plain words: no tags, no stack. A permission error that carries no text says that, in words."""
	text = re.sub(r"<[^>]+>", "", str(exc)).strip()[:300]
	return text or (
		_("insufficient permission") if isinstance(exc, frappe.PermissionError) else _("no reason was given")
	)
