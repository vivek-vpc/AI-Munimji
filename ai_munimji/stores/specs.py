"""The tables of the engine's stores and the DocTypes that hold them: one description, read by the store code (what to convert and where to put it) and by `dev/scripts/make_doctypes.py`
(which writes the DocType files from it). A test (tests/test_store_specs.py) compares the files with what the script writes, so the two cannot drift apart.

No import of frappe here: the script runs outside a bench.

Two ways of keeping a row, chosen per table:
  * COLUMNS (`json_row=False`): the DocType's columns are the row. What a person looks at, filters and is told about is a real column; the engine's own JSON text (a request, an answer,
    a ranking) is a read-only JSON field. Used for approvals, proposals, alerts, notices, work orders, transfers, settings and the rest the Desk will show.
  * JSON ROW (`json_row=True`): the whole engine row is kept as exact JSON in `row_json`, with copies of only the columns that find and expire rows. Used for the logs (runs, tasks, tool
    calls, replies) where nobody filters by most of the fields and volume is the concern.

Kinds of column: data (140 characters), text (Small Text), long (Long Text), json (the engine's JSON text, kept byte for byte), int, float, check (0 or 1), datetime, date.
A float that the engine may leave empty (`null=True`) is stored as a number plus a note of which were empty, because a Frappe number column cannot hold NULL.
A `derived` column is not part of the engine's row: it is worked out from the row when it is written, for the list view and the filters.
An `internal` column is not part of the engine's row either, and is not worked out from it: it is what the app keeps beside the row (whether a request has been sealed, how far a job
got), changed only by the app's stores (`DocTable.set_internal`), so that it survives every write of the engine's row.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Col:
	name: str
	kind: str = "data"
	label: str = ""
	link: str = ""  # a Link to this DocType (the value is kept as given even when no such record exists: see table.py)
	null: bool = False
	flags: str = ""  # l: in the list view, f: a standard filter, i: indexed, u: unique, h: hidden
	derived: bool = False
	internal: bool = False  # the app's own bookkeeping, not part of the engine's row: never in a row the engine reads or writes, only set by the app's stores through `DocTable.set_internal`

	@property
	def title(self) -> str:
		return self.label or self.name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class Table:
	doctype: str
	engine: str  # the table's name in the engine's Protocols
	cols: tuple[Col, ...]
	key: tuple[str, ...] = ("id",)  # the engine columns that make the record's name
	hashed: bool = (
		False  # the name is a hash of the key columns (ids that come from outside, or composite keys)
	)
	numbered: bool = False  # key[0] is a number the store hands out in order: 1, 2, 3 ...
	json_row: bool = False
	perms: dict[str, str] = field(
		default_factory=dict
	)  # role -> r read, w write, c create, x report+export, a approve
	person: bool = False  # a Desk screen of its own is expected (list view, filters, notifications)
	title_field: str = ""
	note: str = ""

	@property
	def name_col(self) -> str:
		return self.key[0]


def d(name, flags="", **kw):
	return Col(name, "data", flags=flags, **kw)


def t(name, flags="", **kw):
	return Col(name, "text", flags=flags, **kw)


def lg(name, flags="", **kw):
	return Col(name, "long", flags=flags, **kw)


def j(name, flags="", **kw):
	return Col(name, "json", flags=flags, **kw)


def n(name, flags="", **kw):
	return Col(name, "int", flags=flags, **kw)


def f(name, flags="", **kw):
	return Col(name, "float", flags=flags, **kw)


def ck(name, flags="", **kw):
	return Col(name, "check", flags=flags, **kw)


def dt(name, flags="", **kw):
	return Col(name, "datetime", flags=flags, **kw)


def da(name, flags="", **kw):
	return Col(name, "date", flags=flags, **kw)


VIEWER, APPROVER, MANAGER, SYSTEM = "Munimji Viewer", "Munimji Approver", "Munimji Manager", "System Manager"
# who may do what, as letters: r read, w write, c create, d delete, x report and export, a approve (the custom permission type)
SCREEN = {
	VIEWER: "rx",
	APPROVER: "rwcx",
	MANAGER: "rwcx",
	SYSTEM: "rwcx",
}  # what a person looks at and answers
ANSWER = {VIEWER: "rx", APPROVER: "rwcxa", MANAGER: "rwcxa", SYSTEM: "rwcxa"}
READ_ONLY_FOR_PEOPLE = {
	MANAGER: "r",
	SYSTEM: "r",
}  # written by the scheduled job (Administrator), read by whoever looks after the app

TABLES: tuple[Table, ...] = (
	Table(
		"Munimji Approval Request",
		"approvals",
		(
			d("kind", "lfi"),
			d("status", "lfi"),
			d("title", "l", derived=True),
			d("severity", "f", derived=True),
			d("item_code", "lfi", link="Item", derived=True),
			d("warehouse", "l", link="Warehouse", derived=True),
			f("qty", "l", derived=True),
			d("supplier", "l", link="Supplier", derived=True),
			d("answer", "f", derived=True, label="Answer"),
			d("approver", "", derived=True, label="Answered by"),
			dt("created_at", "li", label="Requested"),
			dt("expires_at", "i", label="Expires"),
			dt("decided_at", "", label="Answered"),
			dt("last_reminder_at", "", label="Last reminder"),
			n("reminder_count", "", label="Reminders sent"),
			d("ref_type", "i", label="Refers to (type)"),
			d("ref_id", "i", label="Refers to"),
			t("status_note", "", label="Note"),
			j("request_json", "", label="The request, as the engine made it"),
			j("decision_json", "", label="The answer, as the engine recorded it"),
			lg("search_text", "h", derived=True, label="What a search looks in"),
			ck(
				"sealed", "ih", internal=True, label="Sealed"
			),  # the audit sweep looks only at closed requests that are not sealed yet (stores/core.py)
		),
		perms=ANSWER,
		person=True,
		title_field="title",
	),
	Table(
		"Munimji Approval Delivery",
		"deliveries",
		(
			d("approval_id", "li", link="Munimji Approval Request", label="Request"),
			d("recipient_id", "", label="Recipient"),
			d("channel", "lf"),
			d("address", ""),
			d("status", "lf"),
			d("external_id", "i", label="Message id"),
			t("error", ""),
			n("attempts", ""),
			dt("sent_at", "l"),
		),
		numbered=True,
		perms={VIEWER: "r", APPROVER: "r", MANAGER: "r", SYSTEM: "r"},
		note="a separate DocType, not a child table: the engine addresses a delivery by its number and looks messages up across requests",
	),
	Table(
		"Munimji Audit Seal",
		"audit_chain",
		(
			d("at", "l", label="Sealed at"),
			d("source", "lf"),
			d("ref_id", "i", label="Record"),
			d("event", "f"),
			d("digest", ""),
			d("prev", "u", label="Previous hash"),
			d("hash", "", label="Hash"),
		),
		key=("seq",),
		numbered=True,
		perms=READ_ONLY_FOR_PEOPLE,
		note="append only: no role may change or delete a row, and the controller refuses it for everyone",
	),
	Table(
		"Munimji Settings Override",
		"settings_overrides",
		(
			d("scope_type", "lf"),
			d("scope_key", "li"),
			j("data_json", "", label="The values"),
			d("updated_by", "l"),
			dt("updated_at", "l"),
		),
		key=("scope_type", "scope_key"),
		hashed=True,
		perms={VIEWER: "r", APPROVER: "r", MANAGER: "rwcd", SYSTEM: "rwcd"},
		person=True,
	),
	Table(
		"Munimji Settings Change",
		"settings_audit",
		(
			d("ts", "l", label="When"),
			d("actor", "lf"),
			d("scope_type", "f"),
			d("scope_key", "i"),
			d("field", "f"),
			j("old_json", "", label="Before"),
			j("new_json", "", label="After"),
			ck("sealed", "ih", internal=True, label="Sealed"),  # see the approvals table
		),
		numbered=True,
		perms={MANAGER: "rc", SYSTEM: "r"},
	),
	Table(
		"Munimji Work Order",
		"work_orders",
		(
			d("type", "lfi"),
			d("status", "lfi"),
			d("item_code", "l", link="Item", derived=True),
			d("source", "li"),
			dt("created_at", "li", label="Made"),
			dt("updated_at", "", label="Changed"),
			j("payload_json", "", label="What was asked"),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Agent Task",
		"agent_tasks",
		(
			d("agent", "lfi"),
			d("task", "lf"),
			d("status", "lfi"),
			d("approval_id", "i", label="Request"),
			d("asked_by", "l"),
			dt("started_at", "li"),
			dt("finished_at", ""),
			d("provider", "f"),
			d("model", "f"),
			ck("remote", "f"),
			n("prompt_tokens", ""),
			n("output_tokens", ""),
			f("llm_seconds", ""),
		),
		json_row=True,
		perms={APPROVER: "c", MANAGER: "rc", SYSTEM: "r"},
	),
	Table(
		"Munimji Tool Call",
		"tool_calls",
		(
			dt("at", "li"),
			d("actor", "l"),
			d("tool", "lf"),
			d("task_id", "i", label="Task"),
			ck("ok", "f"),
		),
		numbered=True,
		json_row=True,
		perms={APPROVER: "c", MANAGER: "rc", SYSTEM: "r"},
	),
	Table(
		"Munimji Job Run",
		"job_runs",
		(
			dt("last_start", "l"),
			dt("last_end", "l"),
			d("progress", "l", internal=True, label="How far it got"),
			n("requests_made", "", internal=True, label="Requests it made"),
		),
		key=("job",),
		json_row=True,
		perms=READ_ONLY_FOR_PEOPLE,
	),
	Table(
		"Munimji Inbound Seen",
		"inbound_seen",
		(d("channel", "lf"), d("external_id", "i"), dt("seen_at", "li")),
		key=("channel", "external_id"),
		hashed=True,
		json_row=True,
		perms=READ_ONLY_FOR_PEOPLE,
	),
	Table(
		"Munimji Stock Alert",
		"alerts",
		(
			d("item_code", "lfi", link="Item"),
			d("kind", "lf"),
			n("severity", "lf"),
			d("status", "lfi"),
			dt("created_at", "li", label="Raised"),
			dt("updated_at", "", label="Changed"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			dt("snoozed_until", ""),
			dt("suppress_until", ""),
			dt("cooldown_until", ""),
			d("run_id", "", label="Run"),
			t("status_note", "", label="Note"),
			lg("reasoning_text", "", label="Why"),
			j("analysis_json", "", label="The figures, as the engine worked them out"),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Stock Notice",
		"stock_notices",
		(
			d("item_code", "lfi", link="Item"),
			d("level", "lf"),
			d("status", "lfi"),
			dt("created_at", "li", label="Sent"),
			dt("updated_at", "", label="Changed"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			dt("snoozed_until", ""),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Purchase Proposal",
		"proposals",
		(
			d("item_code", "lfi", link="Item"),
			d("status", "lfi"),
			d("work_order_id", "i", link="Munimji Work Order", label="Work order"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			d("supplier", "l", link="Supplier"),
			d("supplier_name", "l"),
			f("qty", "l", null=True),
			f("rate", "", null=True),
			f("total", "l", null=True),
			d("po_name", "l", link="Purchase Order", label="Draft Purchase Order"),
			dt("snoozed_until", ""),
			dt("created_at", "li", label="Made"),
			dt("updated_at", "", label="Changed"),
			t("status_note", "", label="Note"),
			j("ranking_json", "", label="The comparison, reasons and tax figures"),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Agent Run",
		"agent_runs",
		(d("agent", "lfi"), dt("started_at", "li"), dt("finished_at", ""), ck("dry_run", "f")),
		json_row=True,
		perms={
			APPROVER: "c",
			MANAGER: "rc",
			SYSTEM: "r",
		},  # a request a person starts runs the agent in their session, and the run is recorded
	),
	Table(
		"Munimji Assistant Answer",
		"assistant_answers",
		(
			d("cache_key", "i"),
			d("approval_id", "i", label="Request"),
			d("asked_by", "l"),
			dt("created_at", "li"),
		),
		key=("cache_key",),
		hashed=True,
		json_row=True,
		perms={APPROVER: "rwcd", MANAGER: "rwcd", SYSTEM: "r"},
	),
	Table(
		"Munimji Chat Log",
		"chat_log",
		(d("asked_by", "l"), dt("asked_at", "li"), d("intent", "lf"), d("status", "f"), d("source", "f")),
		numbered=True,
		json_row=True,
		perms={APPROVER: "c", MANAGER: "rc", SYSTEM: "r"},
	),
	Table(
		"Munimji Vendor Message",
		"vendor_messages",
		(
			d("purpose", "lf"),
			d("ref_id", "li", label="Order or round"),
			d("supplier", "l"),
			d("channel", "f"),
			d("status", "f"),
			d("approval_id", "i", label="Request"),
			d("address_hash", "i"),
			d("hash_kind", ""),
			dt("sent_at", "li"),
			dt("closed_at", ""),
		),
		json_row=True,
		perms={APPROVER: "rwc", MANAGER: "rwc", SYSTEM: "r"},
	),
	Table(
		"Munimji Vendor Reply",
		"vendor_replies",
		(
			d("message_id", "i", label="Message"),
			d("supplier", "li"),
			d("purpose", "f"),
			d("ref_id", "i", label="Order or round"),
			d("text_hash", "i"),
			n("relayed", ""),
			dt("received_at", "li"),
		),
		numbered=True,
		json_row=True,
		perms={APPROVER: "rwc", MANAGER: "rwc", SYSTEM: "r"},
	),
	Table(
		"Munimji Delivery Chase",
		"delivery_chases",
		(
			d("supplier", "l"),
			d("item_code", "li", link="Item"),
			d("status", "lfi"),
			da("first_late_on", "l"),
			dt("asked_at", ""),
			n("asks", ""),
			dt("sent_at", ""),
			n("sends", ""),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			dt("updated_at", "", label="Changed"),
		),
		key=("po_name",),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Receipt Check",
		"receipt_checks",
		(
			d("supplier", "l"),
			d("status", "lfi"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			dt("checked_at", "li"),
			j("problems_json", "", label="What was found"),
		),
		key=("receipt",),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Quote Round",
		"quote_rounds",
		(
			d("item_code", "lfi", link="Item"),
			f("qty", "l"),
			d("uom", ""),
			d("status", "lfi"),
			da("reply_by", "l"),
			dt("asked_at", ""),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			d("comparison_id", "", label="Comparison"),
			d("requested_by", "l"),
			t("status_note", "", label="Note"),
			dt("created_at", "li", label="Made"),
			dt("updated_at", "", label="Changed"),
			j("suppliers_json", "", label="Suppliers asked"),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Stock Transfer",
		"stock_transfers",
		(
			d("item_code", "lfi", link="Item"),
			f("qty", "l"),
			d("uom", ""),
			d("from_warehouse", "l", link="Warehouse"),
			d("to_warehouse", "l", link="Warehouse"),
			d("status", "lfi"),
			d("entry_name", "l", link="Stock Entry", label="Draft Stock Entry"),
			t("reason", ""),
			d("requested_by", "l"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			t("status_note", "", label="Note"),
			dt("created_at", "li", label="Made"),
			dt("updated_at", "", label="Changed"),
		),
		perms=SCREEN,
		person=True,
	),
	Table(
		"Munimji Cycle Count",
		"cycle_counts",
		(
			d("abc_class", "f", label="ABC class"),
			da("last_counted_on", "l"),
			da("due_on", "li"),
			da("planned_on", ""),
			dt("updated_at", "", label="Changed"),
		),
		key=("item_code",),
		perms={APPROVER: "rwc", MANAGER: "rwc", SYSTEM: "r"},
	),
	Table(
		"Munimji Count Review",
		"count_reviews",
		(
			d("document", "li"),
			d("item_code", "li", link="Item"),
			d("warehouse", "l", link="Warehouse"),
			f("variance", "l"),
			d("approval_id", "i", link="Munimji Approval Request", label="Request"),
			dt("reviewed_at", "li"),
		),
		key=("document", "item_code", "warehouse"),
		hashed=True,
		perms={APPROVER: "rwc", MANAGER: "rwc", SYSTEM: "r"},
	),
	Table(
		"Munimji Lock",
		"locks",
		(
			d("holder", ""),
			dt("until", ""),
			n("counter", ""),
		),
		key=("lock_key",),
		perms={APPROVER: "wc", MANAGER: "wc"},
		note="rows that serialise work: making a document from a request (one per document type), the next number of a numbered table, a scheduled run's lease. Made by install and migrate",
	),
)

BY_DOCTYPE = {table.doctype: table for table in TABLES}
BY_ENGINE = {table.engine: table for table in TABLES}
