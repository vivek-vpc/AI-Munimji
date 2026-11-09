"""The clean-up of the high-volume records: what the agents did, the chat log, the ids of messages already handled.

It deletes only records that have served their purpose and that no person answers or decides: runs, tool calls, task records, the assistant's cached answers, the chat log, messages to
vendors and their replies, the ids of inbound messages. It never touches a request, a proposal, an alert, a notice, a work order, a transfer or anything else a person looks at or answers,
whatever its age, and never the audit seal: those tables are not in RULES, and a test fails if one is.

How long is the setting "Keep logs for (days)" of AI Munimji Settings (90 by default; 0 keeps them all). The other periods are fixed: a task record a year, a vendor message or reply a year,
an assistant answer half a year, an inbound message id a fortnight (it only has to outlive a channel's re-delivery of the same message).

It runs in the system mode (jobs.system_stores()) and is called by hand or by the scheduler (Phase 5 adds its schedule): `bench --site <site> execute ai_munimji.retention.clean_up`.
"""

from datetime import timedelta

import frappe
from ai_munimji_engine.core.common import iso, utcnow

from ai_munimji import jobs
from ai_munimji.settings_map import KEEP_LOGS_DEFAULT
from ai_munimji.stores import frappe_stock_stores

LOGS = "logs"  # the period the setting names
# engine table -> (the column that says how old the record is, how long it is kept in days or LOGS, an extra condition)
RULES: dict[str, tuple[str, int | str, list | None]] = {
	"tool_calls": ("at", LOGS, None),
	"agent_runs": ("started_at", LOGS, None),
	"chat_log": ("asked_at", LOGS, None),
	"agent_tasks": (
		"started_at",
		365,
		[["status", "!=", "running"]],
	),  # a task still running is never deleted
	"assistant_answers": ("created_at", 180, None),
	"vendor_messages": (
		"sent_at",
		365,
		[["closed_at", "is", "set"]],
	),  # an open conversation is never deleted
	"vendor_replies": ("received_at", 365, None),
	"inbound_seen": ("seen_at", 14, None),
}
SETTING = "keep_logs_days"


def clean_up(keep_days: int | None = None, now=None) -> dict[str, int]:
	"""Delete what is old enough. `keep_days` overrides the setting (for a test or a manual run). Returns how many records went, per table. Running it again deletes nothing more."""
	if keep_days is None:
		keep_days = frappe.get_cached_doc("AI Munimji Settings").get(SETTING)
	days = (
		KEEP_LOGS_DEFAULT if keep_days is None else int(keep_days)
	)  # nothing stored (a page saved before the field existed) is the default, not "keep everything"
	now = now or utcnow()
	core = jobs.system_stores()
	stock = frappe_stock_stores(core)
	gone: dict[str, int] = {}
	for engine_table, (column, keep, extra) in RULES.items():
		period = days if keep == LOGS else int(keep)
		if period <= 0:
			continue  # "0" keeps the logs
		table = core.backend.table(engine_table)
		cutoff = iso(now - timedelta(days=period))
		filters = [[column, "<", table.at(cutoff)], *(extra or [])]
		gone[engine_table] = sum(int(table.remove(name)) for name in table.names(filters))
	if (
		days > 0
	):  # then the engine's own: the trace of an old task goes (the task stays), and a vendor's number is forgotten
		cutoff = iso(now - timedelta(days=days))
		gone["task_traces_cleared"] = core.agents.prune(cutoff)
		gone["vendor_numbers_forgotten"] = stock.vendors.forget_hashes_before(cutoff)
	return gone
