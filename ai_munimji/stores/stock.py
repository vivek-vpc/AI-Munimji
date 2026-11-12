"""The stock pack's stores on DocTypes: alerts, notices, proposals, runs, the assistant's answers and chat log, messages to vendors and their replies, delivery chases, receipt checks,
quote rounds, stock transfers and cycle counts. Same contract as the SQLite and memory stores (`ai_munimji_engine.testkit.stores`); see core.py for how a row is kept.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from ai_munimji_engine.stores.stock import StockStores
from ai_munimji_engine.stores.stock.followup import QUOTE_COLUMNS
from ai_munimji_engine.stores.stock.movements import TRANSFER_COLUMNS
from ai_munimji_engine.stores.stock.proposals import UPDATABLE as PROPOSAL_COLUMNS

from ai_munimji.stores.core import Context, _Store
from ai_munimji.stores.table import Exists, Row


def _only(row: Row, keys: Sequence[str]) -> Row:
	return {k: row[k] for k in keys}


NEWEST_LAST_MADE_FIRST = "created_at desc, creation desc"  # SQLite's `ORDER BY created_at DESC, rowid DESC`
NEWEST_FIRST_MADE_FIRST = "created_at desc, creation asc"


class FrappeAlertStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("alerts")

	def insert(
		self,
		alert_id: str,
		item_code: str,
		kind: str,
		severity: int,
		now: str,
		analysis_json: str,
		reasoning_text: str,
		run_id: str | None,
	) -> None:
		self.t.insert(
			{
				"id": alert_id,
				"item_code": item_code,
				"kind": kind,
				"severity": severity,
				"status": "awaiting",
				"created_at": now,
				"updated_at": now,
				"analysis_json": analysis_json,
				"reasoning_text": reasoning_text,
				"approval_id": None,
				"snoozed_until": None,
				"suppress_until": None,
				"cooldown_until": None,
				"status_note": None,
				"run_id": run_id,
			}
		)

	def get(self, alert_id: str) -> Row | None:
		return self.t.get(alert_id)

	def latest_for_item(self, item_code: str) -> Row | None:
		rows = self.t.find([["item_code", "=", item_code]], order_by=NEWEST_LAST_MADE_FIRST, limit=1)
		return rows[0] if rows else None

	def open_for_item(self, item_code: str, statuses: Sequence[str]) -> list[Row]:
		return self.t.find([["item_code", "=", item_code], ["status", "in", list(statuses)]])

	def list(self, status: str | None, item_code: str | None, limit: int) -> list[Row]:
		filters = ([["status", "=", status]] if status else []) + (
			[["item_code", "=", item_code]] if item_code else []
		)
		return self.t.find(filters, order_by=NEWEST_LAST_MADE_FIRST, limit=limit)

	def set_approval(self, alert_id: str, approval_id: str, now: str) -> None:
		self.t.change(alert_id, lambda r: {**r, "approval_id": approval_id, "updated_at": now})

	def update_status(
		self,
		alert_id: str,
		status: str,
		note: str,
		now: str,
		snoozed_until: str | None,
		suppress_until: str | None,
		cooldown_until: str | None,
	) -> None:
		def apply(r: Row) -> Row:
			r.update(status=status, status_note=note, updated_at=now)
			for column, value in (
				("snoozed_until", snoozed_until),
				("suppress_until", suppress_until),
				("cooldown_until", cooldown_until),
			):
				if value is not None:
					r[column] = value
			return r

		self.t.change(alert_id, apply)

	def set_reasoning(self, alert_id: str, text: str) -> None:
		self.t.change(alert_id, lambda r: {**r, "reasoning_text": text})

	def by_approval(self, approval_id: str) -> Row | None:
		rows = self.t.find([["approval_id", "=", approval_id]], limit=1)
		return rows[0] if rows else None


class FrappeNoticeStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("stock_notices")

	def insert(self, notice_id: str, item_code: str, level: str, now: str, approval_id: str | None) -> None:
		self.t.insert(
			{
				"id": notice_id,
				"item_code": item_code,
				"level": level,
				"status": "sent",
				"created_at": now,
				"updated_at": now,
				"approval_id": approval_id,
				"snoozed_until": None,
			}
		)

	def get(self, notice_id: str) -> Row | None:
		return self.t.get(notice_id)

	def by_approval(self, approval_id: str) -> Row | None:
		rows = self.t.find([["approval_id", "=", approval_id]], limit=1)
		return rows[0] if rows else None

	def latest_active(self, item_code: str, statuses: Sequence[str]) -> Row | None:
		rows = self.t.find(
			[["item_code", "=", item_code], ["status", "in", list(statuses)]],
			order_by=NEWEST_LAST_MADE_FIRST,
			limit=1,
		)
		return rows[0] if rows else None

	def active_for_item(self, item_code: str, statuses: Sequence[str]) -> list[Row]:
		return self.t.find([["item_code", "=", item_code], ["status", "in", list(statuses)]])

	def set_approval(self, notice_id: str, approval_id: str, now: str) -> None:
		self.t.change(notice_id, lambda r: {**r, "approval_id": approval_id, "updated_at": now})

	def set_status(self, notice_id: str, status: str, now: str, snoozed_until: str | None) -> None:
		def apply(r: Row) -> Row:
			r.update(status=status, updated_at=now)
			if snoozed_until is not None:
				r["snoozed_until"] = snoozed_until
			return r

		self.t.change(notice_id, apply)

	def list(self, limit: int) -> list[Row]:
		return self.t.find(order_by=NEWEST_LAST_MADE_FIRST, limit=limit)


class FrappeProposalStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("proposals")

	def insert(
		self,
		proposal_id: str,
		work_order_id: str,
		item_code: str,
		status: str,
		supplier: str | None,
		supplier_name: str | None,
		qty: float | None,
		rate: float | None,
		total: float | None,
		ranking_json: str | None,
		note: str,
		now: str,
	) -> None:
		self.t.insert(
			{
				"id": proposal_id,
				"work_order_id": work_order_id,
				"item_code": item_code,
				"status": status,
				"approval_id": None,
				"supplier": supplier,
				"supplier_name": supplier_name,
				"qty": qty,
				"rate": rate,
				"total": total,
				"po_name": None,
				"ranking_json": ranking_json,
				"status_note": note,
				"snoozed_until": None,
				"created_at": now,
				"updated_at": now,
			}
		)

	def get(self, proposal_id: str) -> Row | None:
		return self.t.get(proposal_id)

	def by_approval(self, approval_id: str) -> Row | None:
		rows = self.t.find([["approval_id", "=", approval_id]], limit=1)
		return rows[0] if rows else None

	def for_work_order(self, work_order_id: str) -> Row | None:
		"""The newest proposal made for this work order (a snoozed one that is looked at again gets a new proposal). Not part of the engine's contract: the flow block of a request follows a
		reorder to its purchase request with it."""
		rows = self.t.find(
			[["work_order_id", "=", work_order_id]], order_by="created_at desc, creation desc", limit=1
		)
		return rows[0] if rows else None

	def open_for_item(self, item_code: str, statuses: Sequence[str]) -> list[Row]:
		return self.t.find([["item_code", "=", item_code], ["status", "in", list(statuses)]])

	def snoozed_due(self, now: str) -> list[Row]:
		return self.t.find(
			[
				["status", "=", "snoozed"],
				["snoozed_until", "is", "set"],
				["snoozed_until", "<=", self.t.at(now)],
			]
		)

	def list(self, status: str | None, item_code: str | None, limit: int) -> list[Row]:
		filters = ([["status", "=", status]] if status else []) + (
			[["item_code", "=", item_code]] if item_code else []
		)
		# the contract (and SQLite) order equal times by when they were made: the later first when one item is asked for, the earlier first otherwise
		return self.t.find(
			filters, order_by=NEWEST_LAST_MADE_FIRST if item_code else NEWEST_FIRST_MADE_FIRST, limit=limit
		)

	def set_ranking(self, proposal_id: str, ranking_json: str, now: str) -> None:
		self.t.change(proposal_id, lambda r: {**r, "ranking_json": ranking_json, "updated_at": now})

	def set_approval(self, proposal_id: str, approval_id: str, now: str) -> None:
		self.t.change(proposal_id, lambda r: {**r, "approval_id": approval_id, "updated_at": now})

	def revise(
		self,
		proposal_id: str,
		supplier: str | None,
		supplier_name: str | None,
		qty: float | None,
		rate: float | None,
		total: float | None,
		note: str,
		now: str,
	) -> None:
		self.t.change(
			proposal_id,
			lambda r: {
				**r,
				"supplier": supplier,
				"supplier_name": supplier_name,
				"qty": qty,
				"rate": rate,
				"total": total,
				"status_note": note,
				"updated_at": now,
			},
		)

	def update_status(
		self, proposal_id: str, status: str, note: str, now: str, extra: Mapping[str, Any]
	) -> None:
		unknown = set(extra) - PROPOSAL_COLUMNS
		if unknown:
			raise ValueError(f"cannot set {', '.join(sorted(unknown))}")
		self.t.change(
			proposal_id, lambda r: {**r, "status": status, "status_note": note, "updated_at": now, **extra}
		)


class FrappeAgentRunStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("agent_runs")

	def add(
		self,
		run_id: str,
		agent: str,
		started_at: str,
		finished_at: str | None,
		dry_run: bool,
		summary_json: str | None,
	) -> None:
		self.t.insert(
			{
				"id": run_id,
				"agent": agent,
				"started_at": started_at,
				"finished_at": finished_at,
				"dry_run": int(dry_run),
				"summary_json": summary_json,
			}
		)

	def get(self, run_id: str) -> Row | None:
		return self.t.get(run_id)

	def recent(self, agent: str, limit: int) -> list[Row]:
		rows = self.t.find(
			[["agent", "=", agent], ["dry_run", "=", 0]],
			order_by="started_at desc, creation asc",
			limit=limit,
		)
		return [_only(r, ("started_at", "summary_json")) for r in rows]

	def list(self, limit: int) -> list[Row]:
		return self.t.find(order_by="started_at desc, creation asc", limit=limit)


class FrappeAssistantStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.a = ctx.table("assistant_answers")
		self.c = ctx.table("chat_log")

	def cached_answer(self, cache_key: str) -> str | None:
		row = self.a.get(self.a.name_of({"cache_key": cache_key}))
		return row["result_json"] if row else None

	def put_answer(
		self,
		cache_key: str,
		approval_id: str,
		question: str,
		result_json: str,
		model: str,
		asked_by: str,
		created_at: str,
	) -> None:
		self.a.remove(
			self.a.name_of({"cache_key": cache_key})
		)  # the old row goes and the new one is the latest made, as INSERT OR REPLACE does
		self.a.insert(
			{
				"cache_key": cache_key,
				"approval_id": approval_id,
				"question": question,
				"result_json": result_json,
				"model": model,
				"asked_by": asked_by,
				"created_at": created_at,
			}
		)

	def answers_for(self, approval_id: str) -> list[Row]:
		rows = self.a.find([["approval_id", "=", approval_id]], order_by="created_at asc, creation asc")
		return [_only(r, ("question", "result_json", "asked_by", "created_at")) for r in rows]

	def log_chat(
		self, asked_by: str, asked_at: str, question: str, intent: str, status: str, source: str
	) -> None:
		self.c.insert(
			{
				"asked_by": asked_by,
				"asked_at": asked_at,
				"question": question,
				"intent": intent,
				"status": status,
				"source": source,
			}
		)

	def chats(self, limit: int) -> list[Row]:
		return list(reversed(self.c.find(order_by="id desc", limit=limit))) if limit > 0 else []


class FrappeVendorStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.m = ctx.table("vendor_messages")
		self.r = ctx.table("vendor_replies")

	# ---- messages
	def add_message(
		self,
		message_id: str,
		purpose: str,
		ref_id: str,
		supplier: str,
		channel: str,
		address_hash: str | None,
		hash_kind: str | None,
		status: str,
		error: str | None,
		approval_id: str | None,
		sent_by: str | None,
		sent_at: str,
	) -> None:
		self.m.insert(
			{
				"id": message_id,
				"purpose": purpose,
				"ref_id": ref_id,
				"supplier": supplier,
				"channel": channel,
				"address_hash": address_hash,
				"hash_kind": hash_kind,
				"status": status,
				"error": error,
				"approval_id": approval_id,
				"sent_by": sent_by,
				"sent_at": sent_at,
				"closed_at": None,
			}
		)

	def messages(self, purpose: str, ref_id: str) -> list[Row]:
		rows = self.m.find(
			[["purpose", "=", purpose], ["ref_id", "=", ref_id]], order_by="sent_at asc, creation asc"
		)
		return [
			_only(r, ("id", "supplier", "channel", "status", "error", "approval_id", "sent_at")) for r in rows
		]

	def messages_for_approval(self, approval_id: str) -> list[Row]:
		rows = self.m.find([["approval_id", "=", approval_id]], order_by="sent_at asc, creation asc")
		return [_only(r, ("supplier", "channel", "status", "error", "sent_at")) for r in rows]

	def close_replies(self, purpose: str, ref_id: str, at: str) -> int:
		closed = 0
		for name in self.m.names(
			[["purpose", "=", purpose], ["ref_id", "=", ref_id], ["closed_at", "is", "not set"]]
		):
			closed += int(
				self.m.change(name, lambda r: {**r, "closed_at": at, "address_hash": None}) is not None
			)
		return closed

	def forget_hashes_before(self, cutoff: str) -> int:
		forgotten = 0
		for name in self.m.names([["address_hash", "is", "set"], ["sent_at", "<", self.m.at(cutoff)]]):
			forgotten += int(self.m.change(name, lambda r: {**r, "address_hash": None}) is not None)
		return forgotten

	def open_message(self, address_hash: str, hash_kind: str, since: str) -> Row | None:
		filters = [
			["address_hash", "=", address_hash],
			["status", "=", "sent"],
			["sent_at", ">=", self.m.at(since)],
			["closed_at", "is", "not set"],
		]
		filters.append(["hash_kind", "=", hash_kind] if hash_kind else ["hash_kind", "is", "not set"])
		rows = self.m.find(filters, order_by="sent_at desc, creation asc")
		rows = [
			r for r in rows if (r["hash_kind"] or "") == hash_kind and r["address_hash"] == address_hash
		]  # the database compares ignoring case; a hash is case-sensitive
		return rows[0] if rows else None

	def open_chase_refs(self) -> set[str]:
		return {
			r["ref_id"]
			for r in self.m.select(["ref_id"], [["purpose", "=", "chase"], ["closed_at", "is", "not set"]])
		}

	def last_sent_channel(self, approval_id: str) -> str | None:
		rows = self.m.find(
			[["approval_id", "=", approval_id], ["status", "=", "sent"]],
			order_by="sent_at desc, creation asc",
			limit=1,
		)
		return rows[0]["channel"] if rows else None

	# ---- replies
	def add_reply(
		self,
		message_id: str,
		supplier: str,
		purpose: str,
		ref_id: str,
		channel: str,
		text: str,
		received_at: str,
		relayed: int,
		text_hash: str,
	) -> None:
		self.r.insert(
			{
				"message_id": message_id,
				"supplier": supplier,
				"purpose": purpose,
				"ref_id": ref_id,
				"channel": channel,
				"text": text,
				"received_at": received_at,
				"relayed": relayed,
				"text_hash": text_hash,
			}
		)

	def replies(self, purpose: str, ref_id: str) -> list[Row]:
		rows = self.r.find([["purpose", "=", purpose], ["ref_id", "=", ref_id]], order_by="id asc")
		return [_only(r, ("supplier", "channel", "text", "received_at")) for r in rows]

	def replies_for_approval(self, approval_id: str) -> list[Row]:
		messages = self.m.names([["approval_id", "=", approval_id]])
		if not messages:
			return []
		rows = self.r.find([["message_id", "in", messages]], order_by="id asc")
		return [_only(r, ("supplier", "text", "received_at")) for r in rows]

	def reply_seen(self, supplier: str, text_hash: str, since: str) -> bool:
		rows = self.r.select(
			["text_hash"],
			[
				["supplier", "=", supplier],
				["text_hash", "=", text_hash],
				["received_at", ">=", self.r.at(since)],
			],
		)
		return any(r["text_hash"] == text_hash for r in rows)  # a hash is case-sensitive

	def count_replies(self, supplier: str, since: str, relayed: int | None = None) -> int:
		filters = [["supplier", "=", supplier], ["received_at", ">=", self.r.at(since)]] + (
			[["relayed", "=", relayed]] if relayed is not None else []
		)
		return self.r.count(filters)


class FrappeChaseStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("delivery_chases")

	def get(self, po_name: str) -> Row | None:
		return self.t.get(po_name)

	def start(
		self,
		po_name: str,
		supplier: str,
		item_code: str,
		first_late_on: str,
		asked_at: str,
		approval_id: str,
		now: str,
	) -> None:
		self.t.insert(
			{
				"po_name": po_name,
				"supplier": supplier,
				"item_code": item_code,
				"status": "open",
				"first_late_on": first_late_on,
				"asked_at": asked_at,
				"asks": 1,
				"sent_at": None,
				"sends": 0,
				"approval_id": approval_id,
				"updated_at": now,
			}
		)

	def reopen(self, po_name: str, asked_at: str, approval_id: str, now: str) -> None:
		self.t.change(
			po_name,
			lambda r: {
				**r,
				"status": "open",
				"asked_at": asked_at,
				"asks": r["asks"] + 1,
				"approval_id": approval_id,
				"updated_at": now,
			},
		)

	def open_chases(self) -> list[Row]:
		return self.t.find([["status", "=", "open"]])

	def set_status(self, po_name: str, status: str, now: str) -> None:
		self.t.change(po_name, lambda r: {**r, "status": status, "updated_at": now})

	def record_send(self, po_name: str, now: str) -> None:
		self.t.change(po_name, lambda r: {**r, "sent_at": now, "sends": r["sends"] + 1, "updated_at": now})


class FrappeReceiptStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("receipt_checks")

	def get(self, receipt: str) -> Row | None:
		return self.t.get(receipt)

	def add(
		self,
		receipt: str,
		supplier: str,
		status: str,
		problems_json: str,
		approval_id: str | None,
		checked_at: str,
	) -> None:
		try:
			self.t.insert(
				{
					"receipt": receipt,
					"supplier": supplier,
					"status": status,
					"problems_json": problems_json,
					"approval_id": approval_id,
					"checked_at": checked_at,
				}
			)
		except Exists:
			raise ValueError(f"receipt {receipt} was checked") from None

	def problems_since(self, since: str) -> list[Row]:
		return [
			_only(r, ("supplier", "problems_json"))
			for r in self.t.find([["checked_at", ">=", self.t.at(since)]])
		]

	def acknowledge(self, approval_id: str) -> None:
		for name in self.t.names([["approval_id", "=", approval_id]]):
			self.t.change(name, lambda r: {**r, "status": "acknowledged"})


class FrappeQuoteStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("quote_rounds")

	def insert(
		self,
		round_id: str,
		item_code: str,
		qty: float,
		uom: str,
		suppliers_json: str,
		reply_by: str,
		requested_by: str,
		now: str,
	) -> None:
		self.t.insert(
			{
				"id": round_id,
				"item_code": item_code,
				"qty": qty,
				"uom": uom,
				"suppliers_json": suppliers_json,
				"status": "proposed",
				"reply_by": reply_by,
				"asked_at": None,
				"approval_id": None,
				"comparison_id": None,
				"requested_by": requested_by,
				"status_note": None,
				"created_at": now,
				"updated_at": now,
			}
		)

	def get(self, round_id: str) -> Row | None:
		return self.t.get(round_id)

	def ids(self, status: str | None, limit: int) -> list[str]:
		return self.t.names(
			[["status", "=", status]] if status else [], order_by="created_at desc, creation asc", limit=limit
		)

	def update(self, round_id: str, fields: Mapping[str, Any]) -> None:
		unknown = set(fields) - QUOTE_COLUMNS
		if unknown:
			raise ValueError(f"cannot set {', '.join(sorted(unknown))}")
		self.t.change(round_id, lambda r: {**r, **fields})


class FrappeTransferStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("stock_transfers")

	def insert(
		self,
		transfer_id: str,
		item_code: str,
		qty: float,
		uom: str,
		from_warehouse: str,
		to_warehouse: str,
		reason: str | None,
		requested_by: str,
		now: str,
	) -> None:
		self.t.insert(
			{
				"id": transfer_id,
				"item_code": item_code,
				"qty": qty,
				"uom": uom,
				"from_warehouse": from_warehouse,
				"to_warehouse": to_warehouse,
				"status": "proposed",
				"entry_name": None,
				"reason": reason,
				"requested_by": requested_by,
				"approval_id": None,
				"status_note": None,
				"created_at": now,
				"updated_at": now,
			}
		)

	def get(self, transfer_id: str) -> Row | None:
		return self.t.get(transfer_id)

	def by_approval(self, approval_id: str) -> Row | None:
		rows = self.t.find([["approval_id", "=", approval_id]], limit=1)
		return rows[0] if rows else None

	def list(self, status: str | None, limit: int) -> list[Row]:
		return self.t.find(
			[["status", "=", status]] if status else [], order_by=NEWEST_FIRST_MADE_FIRST, limit=limit
		)

	def update(self, transfer_id: str, fields: Mapping[str, Any]) -> None:
		unknown = set(fields) - TRANSFER_COLUMNS
		if unknown:
			raise ValueError(f"cannot set {', '.join(sorted(unknown))}")
		self.t.change(transfer_id, lambda r: {**r, **fields})


class FrappeCountStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.s = ctx.table("cycle_counts")
		self.r = ctx.table("count_reviews")

	def upsert_schedule(
		self, item_code: str, abc_class: str, last_counted_on: str | None, due_on: str, now: str
	) -> None:
		row = {
			"item_code": item_code,
			"abc_class": abc_class,
			"last_counted_on": last_counted_on,
			"due_on": due_on,
			"planned_on": None,
			"updated_at": now,
		}
		try:
			self.s.insert(row)
		except Exists:
			self.s.change(
				item_code,
				lambda r: {
					**r,
					"abc_class": abc_class,
					"last_counted_on": last_counted_on,
					"due_on": due_on,
					"updated_at": now,
				},
			)  # planned_on stays

	def schedule(self, item_code: str) -> Row | None:
		return self.s.get(item_code)

	def mark_planned(self, item_code: str, planned_on: str) -> None:
		self.s.change(item_code, lambda r: {**r, "planned_on": planned_on})

	def reviewed(self, document: str, item_code: str, warehouse: str) -> bool:
		return (
			self.r.get(self.r.name_of({"document": document, "item_code": item_code, "warehouse": warehouse}))
			is not None
		)

	def add_review(
		self,
		document: str,
		item_code: str,
		warehouse: str,
		variance: float,
		approval_id: str | None,
		now: str,
	) -> None:
		try:
			self.r.insert(
				{
					"document": document,
					"item_code": item_code,
					"warehouse": warehouse,
					"variance": variance,
					"approval_id": approval_id,
					"reviewed_at": now,
				}
			)
		except Exists:
			pass  # already reviewed: left as it is


def frappe_stock_stores(core) -> StockStores:
	"""The stock pack's stores on the same site and in the same mode as the core's: one transaction then covers both."""
	if core.kind != "frappe":
		raise ValueError(f"these are the stock stores for a Frappe site, not for {core.kind!r}")
	ctx = core.backend
	return StockStores(
		alerts=FrappeAlertStore(ctx),
		notices=FrappeNoticeStore(ctx),
		proposals=FrappeProposalStore(ctx),
		runs=FrappeAgentRunStore(ctx),
		assistant=FrappeAssistantStore(ctx),
		vendors=FrappeVendorStore(ctx),
		chases=FrappeChaseStore(ctx),
		receipts=FrappeReceiptStore(ctx),
		quotes=FrappeQuoteStore(ctx),
		transfers=FrappeTransferStore(ctx),
		counts=FrappeCountStore(ctx),
	)
