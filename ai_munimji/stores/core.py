"""The core's stores on DocTypes: approvals and their deliveries, the audit seal, settings overrides and their change record, work orders, the agents' log, job runs, and the ids of
inbound messages. Each class does what the Protocol in `ai_munimji_engine.stores` says and what the shared contract checks (`ai_munimji_engine.testkit.stores`) demand, on the rows of
`specs.py`. Where it cannot be identical to the SQLite stores, the difference is written in docs/STORES.md and pinned by a test.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Any

import frappe
from ai_munimji_engine.stores import CoreStores
from ai_munimji_engine.stores.agents import STALE_NOTE
from frappe import _

from ai_munimji.stores import convert, unit
from ai_munimji.stores.table import DocTable, Exists, Row

SYSTEM_USER = "Administrator"


# ---------------------------------------------------------------------------------------------------------------------- what a list view shows about a row
def _loads(text: str | None) -> dict:
	try:
		value = json.loads(text) if text else {}
	except ValueError:
		return {}
	return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
	try:
		return None if value is None else float(value)
	except (TypeError, ValueError):
		return None


def project_approval(row: Row) -> dict[str, Any]:
	request, decision = _loads(row.get("request_json")), _loads(row.get("decision_json"))
	facts = request.get("facts") if isinstance(request.get("facts"), dict) else {}
	return {
		"title": convert.clip(request.get("title")),
		"severity": convert.clip(request.get("severity")),
		"item_code": convert.clip(facts.get("item_code")),
		"warehouse": convert.clip(facts.get("warehouse")),
		"qty": _number(facts.get("qty")),
		"supplier": convert.clip(facts.get("supplier")),
		"answer": convert.clip(decision.get("action")),
		"approver": convert.clip(decision.get("actor_id")),
		# what search looks in. The JSON fields compare as binary (case and accents count), a Long Text column compares the way the rest of the site does
		"search_text": "\n".join(
			str(row.get(k) or "") for k in ("id", "kind", "request_json", "decision_json", "status_note")
		),
	}


def project_work_order(row: Row) -> dict[str, Any]:
	return {"item_code": convert.clip(_loads(row.get("payload_json")).get("item_code"))}


PROJECTIONS: dict[str, Callable[[Row], dict[str, Any]]] = {
	"approvals": project_approval,
	"work_orders": project_work_order,
}


class Context:
	"""What the stores of one bundle share: whether they run in the named system mode, and the DocTypes they have opened."""

	def __init__(self, system: bool = False) -> None:
		if system and frappe.session.user != SYSTEM_USER:
			raise frappe.PermissionError(
				_("The system mode is for the scheduled job, which runs as Administrator.")
			)
		self.system = system
		self._tables: dict[str, DocTable] = {}

	def table(self, engine_table: str) -> DocTable:
		if engine_table not in self._tables:
			self._tables[engine_table] = DocTable(engine_table, PROJECTIONS.get(engine_table))
		return self._tables[engine_table]

	def need_system(self, what: str) -> None:
		if not self.system:
			raise frappe.PermissionError(
				_("{0} is done by the scheduled job, not in a person's session.").format(what)
			)


class _Store:
	def __init__(self, ctx: Context) -> None:
		self.ctx = ctx

	def transaction(self) -> AbstractContextManager[None]:
		return unit.transaction()


# ---------------------------------------------------------------------------------------------------------------------- approvals
def _has(text: Any, term: str) -> bool:
	return term.lower() in (text or "").lower()


class FrappeApprovalStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.a = ctx.table("approvals")
		self.d = ctx.table("deliveries")

	def _pending(self, approval_id: str, to: dict[str, Any]) -> bool:
		def apply(row: Row) -> Row | None:
			return {**row, **to} if row["status"] == "pending" else None

		return self.a.change(approval_id, apply) is not None

	# ---- requests
	def insert(
		self,
		approval_id: str,
		kind: str,
		request_json: str,
		ref_type: str | None,
		ref_id: str | None,
		created_at: str,
		expires_at: str | None,
	) -> None:
		self.a.insert(
			{
				"id": approval_id,
				"kind": kind,
				"status": "pending",
				"request_json": request_json,
				"decision_json": None,
				"ref_type": ref_type,
				"ref_id": ref_id,
				"created_at": created_at,
				"expires_at": expires_at,
				"decided_at": None,
				"last_reminder_at": None,
				"reminder_count": 0,
				"status_note": None,
			}
		)

	def get(self, approval_id: str) -> Row | None:
		return self.a.get(approval_id)

	def list(self, status: str | None, limit: int) -> list[Row]:
		return self.a.find(
			[["status", "=", status]] if status else [], order_by="created_at desc, creation asc", limit=limit
		)

	def latest_of_kind(self, kind: str) -> Row | None:
		rows = self.a.find([["kind", "=", kind]], order_by="created_at desc, creation asc", limit=1)
		return rows[0] if rows else None

	def due_for_expiry(self, now: str) -> list[str]:
		return self.a.names(
			[["status", "=", "pending"], ["expires_at", "is", "set"], ["expires_at", "<=", self.a.at(now)]]
		)

	def decide_if_pending(self, approval_id: str, decision_json: str, decided_at: str) -> bool:
		return self._pending(
			approval_id, {"status": "decided", "decision_json": decision_json, "decided_at": decided_at}
		)

	def cancel_if_pending(self, approval_id: str, note: str) -> bool:
		return self._pending(approval_id, {"status": "cancelled", "status_note": note})

	def expire_if_pending(self, approval_id: str) -> bool:
		return self._pending(approval_id, {"status": "expired"})

	def add_reminder(self, approval_id: str, at: str) -> None:
		self.a.change(
			approval_id, lambda r: {**r, "reminder_count": r["reminder_count"] + 1, "last_reminder_at": at}
		)

	def search(
		self,
		terms: list[str],
		kind: str | None,
		status: str | None,
		since: str | None,
		before: str | None,
		limit: int,
	) -> list[Row]:
		# The database narrows by status and by every term (a superset: MariaDB compares ignoring case and accents, and the JSON fields are binary, so the terms are looked for in a
		# copy of the text that is not); the rules of the Protocol are then applied to what is left, exactly.
		filters = ([["status", "=", status]] if status else []) + [
			["search_text", "like", convert.like_pattern(t)] for t in terms
		]
		out: list[Row] = []
		for r in self.a.find(filters, order_by="created_at desc, creation asc"):
			if any(
				not (
					_has(r["request_json"], t)
					or _has(r["decision_json"], t)
					or _has(r["status_note"], t)
					or _has(r["kind"], t)
					or r["id"] == t
				)
				for t in terms
			):
				continue
			if (
				(kind and not _has(r["kind"], kind))
				or (status and r["status"] != status)
				or (since and not r["created_at"] >= since)
				or (before and not r["created_at"] < before)
			):
				continue
			out.append(r)
			if len(out) >= limit:
				break
		return out

	def decision_texts(self) -> list[str]:
		return [
			r["decision_json"] for r in self.a.select(["decision_json"], [["decision_json", "is", "set"]])
		]

	def with_reference(self, ref_type: str | None, ref_id: str | None, exclude_id: str) -> list[Row]:
		if ref_type is None or ref_id is None:  # in SQL `ref_type = NULL` is never true
			return []
		rows = self.a.find(
			[["ref_type", "=", ref_type], ["ref_id", "=", ref_id], ["name", "!=", exclude_id]],
			order_by="created_at asc, creation asc",
		)
		return [{k: r[k] for k in ("id", "kind", "status", "created_at", "status_note")} for r in rows]

	# ---- counts for the monitoring
	def pending_summary(self) -> Row:
		rows = self.a.select(["created_at"], [["status", "=", "pending"]])
		return {"n": len(rows), "oldest": min((r["created_at"] for r in rows), default=None)}

	def outcome_counts(self) -> list[Row]:
		counts: dict[tuple[str, str], int] = defaultdict(int)
		for r in self.a.select(["kind", "status", "decision_json"], [["status", "!=", "pending"]]):
			action = _loads(r["decision_json"]).get("action") or r["status"]
			counts[(r["kind"], action)] += 1
		return [{"kind": k, "outcome": o, "n": n} for (k, o), n in sorted(counts.items())]

	def delivery_counts(self) -> list[Row]:
		counts: dict[tuple[str, str], int] = defaultdict(int)
		for r in self.d.select(["channel", "status"]):
			counts[(r["channel"], r["status"])] += 1
		return [{"channel": c, "status": s, "n": n} for (c, s), n in sorted(counts.items())]

	# ---- deliveries
	def add_delivery(
		self,
		approval_id: str,
		recipient_id: str,
		channel: str,
		address: str | None,
		status: str,
		external_id: str | None,
		error: str | None,
		sent_at: str,
	) -> None:
		self.d.insert(
			{
				"approval_id": approval_id,
				"recipient_id": recipient_id,
				"channel": channel,
				"address": address,
				"status": status,
				"external_id": external_id,
				"error": error,
				"attempts": 1,
				"sent_at": sent_at,
			}
		)

	def deliveries(self, approval_id: str, status: str | None = None) -> list[Row]:
		filters = [["approval_id", "=", approval_id]] + (
			[["status", "=", status]] if status is not None else []
		)
		return self.d.find(filters, order_by="id asc")

	def failed_deliveries(self, max_attempts: int) -> list[Row]:
		failed = self.d.find([["status", "=", "failed"], ["attempts", "<", max_attempts]], order_by="id asc")
		if not failed:
			return []
		pending = set(
			self.a.names(
				[["name", "in", sorted({r["approval_id"] for r in failed})], ["status", "=", "pending"]]
			)
		)
		return [r for r in failed if r["approval_id"] in pending]

	def update_delivery(
		self,
		delivery_id: int,
		status: str,
		external_id: str | None,
		error: str | None,
		attempts: int,
		sent_at: str,
	) -> None:
		self.d.change(
			str(delivery_id),
			lambda r: {
				**r,
				"status": status,
				"external_id": external_id,
				"error": error,
				"attempts": attempts,
				"sent_at": sent_at,
			},
		)

	def approval_for_message(self, channel: str, external_id: str, address: str) -> str | None:
		rows = self.d.find(
			[["channel", "=", channel], ["external_id", "=", external_id], ["address", "=", address]],
			order_by="id desc",
			limit=1,
		)
		return rows[0]["approval_id"] if rows else None


# ---------------------------------------------------------------------------------------------------------------------- the seal
class FrappeAuditStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.s = ctx.table("audit_chain")
		self.a = ctx.table("approvals")
		self.c = ctx.table("settings_audit")

	def is_empty(self) -> bool:
		return not self.s.names(limit=1)

	def last_hash(self) -> str | None:
		rows = self.s.select(["hash"], order_by="seq desc", limit=1)
		return rows[0]["hash"] if rows else None

	def append(
		self, at: str, source: str, ref_id: str, event: str, digest: str, prev: str, hash_: str
	) -> None:
		self.ctx.need_system("sealing")
		self.s.insert(
			{
				"at": at,
				"source": source,
				"ref_id": ref_id,
				"event": event,
				"digest": digest,
				"prev": prev,
				"hash": hash_,
			}
		)

	def entries(self) -> list[Row]:
		return self.s.find(order_by="seq asc")

	def sealed_at(self, source: str, ref_id: str) -> str | None:
		rows = self.s.select(
			["at"], [["source", "=", source], ["ref_id", "=", ref_id]], order_by="seq asc", limit=1
		)
		return rows[0]["at"] if rows else None

	def _unsealed(self) -> list[Row]:
		sealed = {r["ref_id"] for r in self.s.select(["ref_id"], [["source", "=", "approval"]])}
		closed = self.a.select(["decided_at", "created_at"], [["status", "!=", "pending"]])
		todo = [r for r in closed if r["name"] not in sealed]
		todo.sort(key=lambda r: (r["decided_at"] or r["created_at"] or "", r["name"]))
		return todo

	def unsealed_approvals(self) -> list[Row]:
		return [row for r in self._unsealed() if (row := self.a.get(r["name"])) is not None]

	def unsealed_count(self) -> int:
		return len(self._unsealed())

	def last_sealed_setting(self) -> int:
		return max(
			(int(r["ref_id"]) for r in self.s.select(["ref_id"], [["source", "=", "setting"]])), default=0
		)

	def settings_after(self, setting_id: int) -> list[Row]:
		return self.c.find([["id", ">", setting_id]], order_by="id asc")

	def current_approval(self, ref_id: str) -> Row | None:
		return self.a.get(ref_id)

	def current_setting(self, setting_id: int) -> Row | None:
		return self.c.get(str(setting_id))


# ---------------------------------------------------------------------------------------------------------------------- settings
class FrappeSettingsOverrideStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.o = ctx.table("settings_overrides")
		self.c = ctx.table("settings_audit")

	def _name(self, scope_type: str, scope_key: str) -> str:
		return self.o.name_of({"scope_type": scope_type, "scope_key": scope_key})

	def get(self, scope_type: str, scope_key: str) -> str | None:
		row = self.o.get(self._name(scope_type, scope_key))
		return row["data_json"] if row else None

	def save(
		self,
		scope_type: str,
		scope_key: str,
		data_json: str | None,
		actor: str,
		now: str,
		changes: list[tuple[str, str, str]],
	) -> None:
		with unit.transaction():
			if data_json is not None:
				self.o.put(
					{
						"scope_type": scope_type,
						"scope_key": scope_key,
						"data_json": data_json,
						"updated_by": actor,
						"updated_at": now,
					}
				)
			else:
				self.o.remove(self._name(scope_type, scope_key))
			for field, old_json, new_json in changes:
				self.c.insert(
					{
						"ts": now,
						"actor": actor,
						"scope_type": scope_type,
						"scope_key": scope_key,
						"field": field,
						"old_json": old_json,
						"new_json": new_json,
					}
				)

	def audit(self, limit: int, scope_type: str | None = None, scope_key: str | None = None) -> list[Row]:
		filters = ([["scope_type", "=", scope_type]] if scope_type else []) + (
			[["scope_key", "=", scope_key]] if scope_key else []
		)
		return self.c.find(filters, order_by="id desc", limit=limit)

	def audit_actors(self) -> list[str]:
		return sorted({r["actor"] for r in self.c.select(["actor"])})


# ---------------------------------------------------------------------------------------------------------------------- work orders
class FrappeWorkOrderStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.w = ctx.table("work_orders")

	def insert(self, wo_id: str, type_: str, payload_json: str, source: str, now: str) -> None:
		self.w.insert(
			{
				"id": wo_id,
				"type": type_,
				"status": "pending",
				"payload_json": payload_json,
				"source": source,
				"created_at": now,
				"updated_at": now,
			}
		)

	def get(self, wo_id: str) -> Row | None:
		return self.w.get(wo_id)

	def list(self, status: str | None, type_: str | None, limit: int) -> list[Row]:
		filters = ([["status", "=", status]] if status else []) + ([["type", "=", type_]] if type_ else [])
		return self.w.find(filters, order_by="created_at desc, creation asc", limit=limit)

	def set_status(self, wo_id: str, status: str, now: str) -> None:
		self.w.change(wo_id, lambda r: {**r, "status": status, "updated_at": now})


# ---------------------------------------------------------------------------------------------------------------------- the agents' log
class FrappeAgentLogStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.t = ctx.table("agent_tasks")
		self.c = ctx.table("tool_calls")

	# ---- tool calls
	def add_tool_call(
		self,
		at: str,
		actor: str,
		via: str,
		tool: str,
		args_json: str,
		ok: bool,
		ms: int,
		task_id: str | None,
		error: str | None,
	) -> None:
		self.c.insert(
			{
				"at": at,
				"actor": actor,
				"via": via,
				"tool": tool,
				"args_json": args_json,
				"ok": int(ok),
				"ms": ms,
				"task_id": task_id,
				"error": error,
			}
		)

	def tool_calls(self, task_id: str | None, limit: int) -> list[Row]:
		if task_id:
			return self.c.find([["task_id", "=", task_id]], order_by="id asc")
		return self.c.find(order_by="id desc", limit=limit)

	# ---- tasks
	def add_task(
		self,
		task_id: str,
		agent: str,
		task: str,
		started_at: str,
		model: str,
		provider: str,
		remote: bool,
		approval_id: str | None,
		asked_by: str,
		request_text: str,
	) -> None:
		self.t.insert(
			{
				"id": task_id,
				"agent": agent,
				"task": task,
				"status": "running",
				"started_at": started_at,
				"finished_at": None,
				"model": model,
				"provider": provider,
				"remote": int(remote),
				"steps": 0,
				"tool_calls": 0,
				"llm_seconds": None,
				"prompt_tokens": None,
				"output_tokens": None,
				"approval_id": approval_id,
				"asked_by": asked_by,
				"request_text": request_text,
				"result_json": None,
				"note": None,
				"trace_json": None,
			}
		)

	def finish_task(
		self,
		task_id: str,
		status: str,
		finished_at: str,
		result_json: str | None,
		note: str,
		steps: int,
		tool_calls: int,
		llm_seconds: float,
		prompt_tokens: int,
		output_tokens: int,
		trace_json: str,
	) -> None:
		self.t.change(
			task_id,
			lambda r: {
				**r,
				"status": status,
				"finished_at": finished_at,
				"result_json": result_json,
				"note": note,
				"steps": steps,
				"tool_calls": tool_calls,
				"llm_seconds": llm_seconds,
				"prompt_tokens": prompt_tokens,
				"output_tokens": output_tokens,
				"trace_json": trace_json,
			},
		)

	def get(self, task_id: str) -> Row | None:
		return self.t.get(task_id)

	def list(self, agent: str | None, task: str | None, approval_id: str | None, limit: int) -> list[Row]:
		filters = (
			([["agent", "=", agent]] if agent else [])
			+ ([["task", "=", task]] if task else [])
			+ ([["approval_id", "=", approval_id]] if approval_id else [])
		)
		return self.t.find(filters, order_by="started_at desc, creation desc", limit=limit)

	def latest(self, agent: str, task: str, status: str) -> Row | None:
		rows = self.t.find(
			[["agent", "=", agent], ["task", "=", task], ["status", "in", [status, "fallback"]]],
			order_by="started_at desc, creation desc",
			limit=1,
		)
		return rows[0] if rows else None

	def tasks_about(self, approval_id: str, marker: str) -> list[Row]:
		rows = [
			r
			for r in self.t.find(order_by="started_at asc, creation asc")
			if r["approval_id"] == approval_id
			or (r["result_json"] and marker.lower() in r["result_json"].lower())
		]
		return rows

	def _since(self, since: str, columns: Sequence[str]) -> list[Row]:
		return self.t.select(columns, [["started_at", ">=", self.t.at(since)]])

	def tokens_since(self, since: str, hosted_only: bool) -> int:
		return sum(
			(r["prompt_tokens"] or 0) + (r["output_tokens"] or 0)
			for r in self._since(since, ["prompt_tokens", "output_tokens", "remote"])
			if not hosted_only or r["remote"] == 1
		)

	def usage_by_model(self, since: str) -> list[Row]:
		groups: dict[tuple[Any, ...], Row] = {}
		for r in self._since(
			since, ["provider", "model", "remote", "prompt_tokens", "output_tokens", "llm_seconds"]
		):
			key = (r["provider"] or "ollama", r["model"], r["remote"])
			g = groups.setdefault(
				key,
				{
					"provider": key[0],
					"model": key[1],
					"remote": key[2],
					"tasks": 0,
					"tokens_in": 0,
					"tokens_out": 0,
					"seconds": 0,
				},
			)
			g["tasks"] += 1
			g["tokens_in"] += r["prompt_tokens"] or 0
			g["tokens_out"] += r["output_tokens"] or 0
			g["seconds"] += r["llm_seconds"] or 0
		ordered = sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1] or ""), kv[0][2]))
		return sorted((g for _, g in ordered), key=lambda g: g["tokens_in"] + g["tokens_out"], reverse=True)

	def usage_by_day(self, since: str) -> list[Row]:
		groups: dict[tuple[Any, ...], Row] = {}
		for r in self._since(since, ["started_at", "remote", "prompt_tokens", "output_tokens"]):
			key = (r["started_at"][:10], r["remote"])
			g = groups.setdefault(
				key, {"day": key[0], "remote": key[1], "tokens_in": 0, "tokens_out": 0, "tasks": 0}
			)
			g["tokens_in"] += r["prompt_tokens"] or 0
			g["tokens_out"] += r["output_tokens"] or 0
			g["tasks"] += 1
		return [g for _, g in sorted(groups.items())]

	def metrics_snapshot(self) -> list[Row]:
		groups: dict[tuple[Any, ...], Row] = {}
		for r in self.t.select(
			["agent", "task", "status", "provider", "model", "prompt_tokens", "output_tokens"]
		):
			key = (r["agent"], r["task"], r["status"], r["provider"] or "ollama", r["model"] or "")
			g = groups.setdefault(
				key,
				{
					"agent": key[0],
					"task": key[1],
					"status": key[2],
					"provider": key[3],
					"model": key[4],
					"n": 0,
					"tokens_in": 0,
					"tokens_out": 0,
				},
			)
			g["n"] += 1
			g["tokens_in"] += r["prompt_tokens"] or 0
			g["tokens_out"] += r["output_tokens"] or 0
		return [g for _, g in sorted(groups.items())]

	def fail_stale(self, now: str, cutoff: str) -> int:
		failed = 0
		for name in self.t.names([["status", "=", "running"], ["started_at", "<", self.t.at(cutoff)]]):
			if self.t.change(
				name,
				lambda r: {**r, "status": "failed", "finished_at": now, "note": STALE_NOTE}
				if r["status"] == "running"
				else None,
			):
				failed += 1
		return failed

	def prune(self, cutoff: str) -> int:
		cleared = 0
		for r in self.t.find([["started_at", "<", self.t.at(cutoff)]]):
			if r["trace_json"] is not None and self.t.change(
				r["id"], lambda row: {**row, "trace_json": None}
			):
				cleared += 1
		for name in self.c.names([["at", "<", self.c.at(cutoff)]]):
			self.c.remove(name)
		return cleared


# ---------------------------------------------------------------------------------------------------------------------- what the scheduler has done
class FrappeJobRunStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.j = ctx.table("job_runs")

	def started(self, job: str, at: str) -> None:
		try:
			self.j.insert(
				{
					"job": job,
					"last_start": at,
					"last_end": None,
					"last_ok": None,
					"last_error": None,
					"runs": 1,
					"failures": 0,
				}
			)
		except Exists:
			self.j.change(job, lambda r: {**r, "last_start": at, "runs": r["runs"] + 1})

	def finished(self, job: str, at: str, ok: bool, error: str | None) -> None:
		self.j.change(
			job,
			lambda r: {
				**r,
				"last_end": at,
				"last_ok": int(ok),
				"last_error": error,
				"failures": r["failures"] + int(not ok),
			},
		)

	def get(self, job: str) -> Row | None:
		return self.j.get(job)

	def all(self) -> list[Row]:
		return self.j.find(order_by="name asc")


# ---------------------------------------------------------------------------------------------------------------------- the ids of inbound messages
class FrappeInboundSeenStore(_Store):
	def __init__(self, ctx: Context) -> None:
		super().__init__(ctx)
		self.i = ctx.table("inbound_seen")

	def claim(self, channel: str, external_id: str, seen_at: str) -> bool:
		try:
			self.i.insert({"channel": channel, "external_id": external_id, "seen_at": seen_at})
			return True
		except Exists:
			return False

	def release(self, channel: str, external_id: str) -> None:
		self.i.remove(self.i.name_of({"channel": channel, "external_id": external_id}))

	def purge_before(self, cutoff: str) -> int:
		gone = 0
		for name in self.i.names([["seen_at", "<", self.i.at(cutoff)]]):
			gone += int(self.i.remove(name))
		return gone


# ---------------------------------------------------------------------------------------------------------------------- the bundle
def health() -> list[tuple[str, bool, str]]:
	return [
		("database", True, "the site's own database"),
		("migrations", True, "Frappe migrates the DocTypes with the app"),
	]


def frappe_core_stores(system: bool = False) -> CoreStores:
	"""The core's stores on this site's DocTypes. `system=True` is the scheduled job's mode: Administrator only, and the only one that may append to the audit seal."""
	ctx = Context(system)
	return CoreStores(
		kind="frappe",
		transaction=unit.transaction,
		approvals=FrappeApprovalStore(ctx),
		audit=FrappeAuditStore(ctx),
		settings=FrappeSettingsOverrideStore(ctx),
		workorders=FrappeWorkOrderStore(ctx),
		agents=FrappeAgentLogStore(ctx),
		jobs=FrappeJobRunStore(ctx),
		inbound=FrappeInboundSeenStore(ctx),
		db=None,
		backend=ctx,
		close=lambda: None,
		health=health,
	)
