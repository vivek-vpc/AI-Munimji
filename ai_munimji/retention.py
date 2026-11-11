"""The clean-up of the high-volume records: what the agents did, the chat log, the ids of messages already handled.

It deletes only records that have served their purpose and that no person answers or decides: runs, tool calls, task records, the assistant's cached answers, the chat log, messages to
vendors and their replies, the ids of inbound messages. It never touches a request, a proposal, an alert, a notice, a work order, a transfer or anything else a person looks at or answers,
whatever its age, and never the audit seal: those tables are not in RULES, and a test fails if one is.

How long is the setting "Keep logs for (days)" of AI Munimji Settings (90 by default; 0 keeps them all). The other periods are fixed: a task record a year, a vendor message or reply a year,
an assistant answer half a year, an inbound message id a fortnight (it only has to outlive a channel's re-delivery of the same message).

It runs in the system mode (jobs.system_stores()). The scheduler calls it once a day (schedule.sync_clean_up), while "Keep logs for (days)" is a positive number; with 0 the job is stopped and
nothing is cleaned up by itself, the fixed periods included. It can also be called by hand: `bench --site <site> execute ai_munimji.retention.clean_up`.

How much one run removes is bounded: at most CAP records, oldest first, in batches of BATCH with a commit after each, a table at a time in turn so that none is starved, and only as fast as the workers take the background jobs that
each deletion queues. A site that has never been
cleaned up has a backlog of any size; a run that tried to remove all of it in one transaction would run out of time and roll back everything, every day, and never make progress. This one always
does: what it removed stays removed, and the next run goes on from the oldest that is left.
"""

import time
from datetime import timedelta

import frappe
from ai_munimji_engine.core.common import iso, utcnow

from ai_munimji import jobs
from ai_munimji.settings_map import KEEP_LOGS_DEFAULT
from ai_munimji.stores import frappe_stock_stores

CAP = 5000  # records one run removes at most (a first backlog is cleared over several runs)
BATCH = 100  # records removed between two commits: each deletion queues a background job (below), and a batch needs room in the queue for its own
QUEUE = "default"  # where Frappe queues those jobs (`frappe.model.delete_doc.delete_dynamic_links`, one for every document deleted)
QUEUE_WAIT_SECONDS = 30  # the longest the run waits for the workers to catch up before it ends, leaving the rest for the next run
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


def room_in_the_queue(jobs_needed: int) -> bool:
	"""Deleting a document queues one background job, and Frappe refuses to queue more than `max_queued_jobs` (500 unless the site says otherwise, plus 50 for each site of the bench): past
	that every deletion raises `QueueOverloaded`. Workers that are slower than the deletions (one worker, or a busy site) would stop a long clean-up half way with an error."""
	from frappe.utils import cint
	from frappe.utils.background_jobs import MAX_QUEUED_JOBS, get_queue

	limit = cint(frappe.conf.max_queued_jobs) or MAX_QUEUED_JOBS
	return cint(get_queue(QUEUE).count) + jobs_needed < limit


def wait_for_room(jobs_needed: int) -> bool:
	"""True when the queue has room for `jobs_needed` more jobs, after waiting up to QUEUE_WAIT_SECONDS for the workers to take what is there."""
	waited = 0
	while not room_in_the_queue(jobs_needed):
		if waited >= QUEUE_WAIT_SECONDS:
			return False
		time.sleep(1)
		waited += 1
	return True


def clean_up(keep_days: int | None = None, now=None, cap: int = CAP, batch: int = BATCH) -> dict[str, int]:
	"""Delete what is old enough, at most `cap` records in all, oldest first. `keep_days` overrides the setting (for a test or a manual run). Returns how many records went, per table;
	when it stopped at the cap, also under "left_for_the_next_run" how many tables may still hold expired records. Running it again removes the next `cap`; when nothing is left it removes nothing."""
	if keep_days is None:
		keep_days = frappe.get_cached_doc("AI Munimji Settings").get(SETTING)
	days = (
		KEEP_LOGS_DEFAULT if keep_days is None else int(keep_days)
	)  # nothing stored (a page saved before the field existed) is the default, not "keep everything"
	now = now or utcnow()
	core = jobs.system_stores()
	stock = frappe_stock_stores(core)
	gone: dict[str, int] = {}
	waiting = {}  # engine table -> (its table, the oldest-first filter, the column), for every table that may still hold expired records
	for engine_table, (column, keep, extra) in RULES.items():
		period = days if keep == LOGS else int(keep)
		if period <= 0:
			continue  # "0" keeps the logs
		table = core.backend.table(engine_table)
		cutoff = iso(now - timedelta(days=period))
		waiting[engine_table] = (table, [[column, "<", table.at(cutoff)], *(extra or [])], column)
		gone[engine_table] = 0
	removed = 0
	while waiting and removed < cap:
		for engine_table in list(waiting):
			table, filters, column = waiting[engine_table]
			asked = min(batch, cap - removed)
			if not wait_for_room(asked):  # the workers have not taken the last batches' jobs yet: end here, and the next run goes on
				cap = removed
				break
			names = table.names(filters, order_by=f"{column} asc", limit=asked)
			for name in names:
				gone[engine_table] += int(table.remove(name))
			removed += len(names)
			if names:
				jobs.commit()  # what is removed stays removed: a later failure or a timeout takes back this batch at most
			if len(names) < asked:  # fewer than asked for: this table has nothing expired left
				del waiting[engine_table]
			if removed >= cap:
				break
	if waiting and removed >= cap:
		gone["left_for_the_next_run"] = len(
			waiting
		)  # the tables that may still hold expired records: the next run goes on with them
	if (
		days > 0
	):  # then the engine's own: the trace of an old task goes (the task stays), and a vendor's number is forgotten
		cutoff = iso(now - timedelta(days=days))
		gone["task_traces_cleared"] = core.agents.prune(
			cutoff, tool_calls=False
		)  # the tool calls went above, capped
		gone["vendor_numbers_forgotten"] = stock.vendors.forget_hashes_before(cutoff)
		jobs.commit()
	return gone
