# How the engine's records are kept on a site

The rules in `ai-munimji-engine` keep what they need to remember (requests and their answers, proposals, alerts, work orders, the agents' log, the seal over the decision history) behind 18
storage interfaces ("stores"). The standalone service keeps them in SQLite. This app keeps them in DocTypes of the site's own database, so that a person sees them in the Desk, Frappe's
permissions say who may read and answer them, and they are backed up and migrated with the site. The code is `ai_munimji/stores/`; the engine's own 60 checks of a store
(`ai_munimji_engine.testkit.stores`) run on it unchanged.

Not part of version 0.1: the Desk screens (list views, the approval form with the reasoning, the inbox, notifications) and the real schedule of the job. The DocTypes carry what those
screens need: real columns to filter and sort by, and the engine's own text kept whole.

## The 25 DocTypes

Roles: **V** Munimji Viewer, **A** Munimji Approver, **M** Munimji Manager, **S** System Manager. "Adm" is Administrator, which is how Frappe runs the scheduled job. Rights: r read, w write, c create,
d delete, x report and export, a approve. A table with no row for a role gives that role nothing. **Kept** says how a row is held: *columns* means the columns are the record and the
engine's own JSON text is a read-only JSON field; *json row* means the whole engine row is kept as exact JSON, with copies of only the columns that find and expire rows. A column in square brackets
is **the app's own**, not part of the engine's row: it is never in a row the engine reads or writes and a write of the row leaves it as it is. There are three: `sealed` on a request and on a settings change
(set when its entry is appended to the audit seal, so that the sweep reads only what is new), and `progress` on a Job Run (how far a long run has got).

<!-- stores-table:begin -->
| DocType | Engine table | Kept | Columns (derived ones in round brackets, the app's own in square brackets) | JSON | Rights | For a person's screen |
|---|---|---|---|---|---|---|
| Munimji Approval Request | `approvals` | columns | kind, status, (title), (severity), (item_code), (warehouse), (qty), (supplier), (answer), (approver), created_at, expires_at, decided_at, last_reminder_at, reminder_count, ref_type, ref_id, status_note, (search_text), [sealed] | request_json, decision_json | V rx; A rwcxa; M rwcxa; S rwcxa | yes |
| Munimji Approval Delivery | `deliveries` | columns | id, approval_id, recipient_id, channel, address, status, external_id, error, attempts, sent_at | none | V r; A r; M r; S r | no |
| Munimji Audit Seal | `audit_chain` | columns | seq, at, source, ref_id, event, digest, prev, hash | none | M r; S r | no |
| Munimji Settings Override | `settings_overrides` | columns | scope_type, scope_key, updated_by, updated_at | data_json | V r; A r; M rwcd; S rwcd | yes |
| Munimji Settings Change | `settings_audit` | columns | id, ts, actor, scope_type, scope_key, field, [sealed] | old_json, new_json | M rc; S r | no |
| Munimji Work Order | `work_orders` | columns | type, status, (item_code), source, created_at, updated_at | payload_json | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Agent Task | `agent_tasks` | json row | agent, task, status, approval_id, asked_by, started_at, finished_at, provider, model, remote, prompt_tokens, output_tokens, llm_seconds | the whole row (`row_json`) | A c; M rc; S r | no |
| Munimji Tool Call | `tool_calls` | json row | id, at, actor, tool, task_id, ok | the whole row (`row_json`) | A c; M rc; S r | no |
| Munimji Job Run | `job_runs` | json row | last_start, last_end, [progress] | the whole row (`row_json`) | M r; S r | no |
| Munimji Inbound Seen | `inbound_seen` | json row | channel, external_id, seen_at | the whole row (`row_json`) | M r; S r | no |
| Munimji Stock Alert | `alerts` | columns | item_code, kind, severity, status, created_at, updated_at, approval_id, snoozed_until, suppress_until, cooldown_until, run_id, status_note, reasoning_text | analysis_json | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Stock Notice | `stock_notices` | columns | item_code, level, status, created_at, updated_at, approval_id, snoozed_until | none | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Purchase Proposal | `proposals` | columns | item_code, status, work_order_id, approval_id, supplier, supplier_name, qty, rate, total, po_name, snoozed_until, created_at, updated_at, status_note | ranking_json | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Agent Run | `agent_runs` | json row | agent, started_at, finished_at, dry_run | the whole row (`row_json`) | A c; M rc; S r | no |
| Munimji Assistant Answer | `assistant_answers` | json row | cache_key, approval_id, asked_by, created_at | the whole row (`row_json`) | A rwcd; M rwcd; S r | no |
| Munimji Chat Log | `chat_log` | json row | id, asked_by, asked_at, intent, status, source | the whole row (`row_json`) | A c; M rc; S r | no |
| Munimji Vendor Message | `vendor_messages` | json row | purpose, ref_id, supplier, channel, status, approval_id, address_hash, hash_kind, sent_at, closed_at | the whole row (`row_json`) | A rwc; M rwc; S r | no |
| Munimji Vendor Reply | `vendor_replies` | json row | id, message_id, supplier, purpose, ref_id, text_hash, relayed, received_at | the whole row (`row_json`) | A rwc; M rwc; S r | no |
| Munimji Delivery Chase | `delivery_chases` | columns | supplier, item_code, status, first_late_on, asked_at, asks, sent_at, sends, approval_id, updated_at | none | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Receipt Check | `receipt_checks` | columns | supplier, status, approval_id, checked_at | problems_json | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Quote Round | `quote_rounds` | columns | item_code, qty, uom, status, reply_by, asked_at, approval_id, comparison_id, requested_by, status_note, created_at, updated_at | suppliers_json | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Stock Transfer | `stock_transfers` | columns | item_code, qty, uom, from_warehouse, to_warehouse, status, entry_name, reason, requested_by, approval_id, status_note, created_at, updated_at | none | V rx; A rwcx; M rwcx; S rwcx | yes |
| Munimji Cycle Count | `cycle_counts` | columns | abc_class, last_counted_on, due_on, planned_on, updated_at | none | A rwc; M rwc; S r | no |
| Munimji Count Review | `count_reviews` | columns | document, item_code, warehouse, variance, approval_id, reviewed_at | none | A rwc; M rwc; S r | no |
| Munimji Lock | `locks` | columns | holder, until, counter | none | A wc; M wc | no |
<!-- stores-table:end -->

The names of the records are the engine's own ids. Ids that come from outside (a message id, a cache key) or are made of several columns are named by a hash of them, in lowercase hex, because
the database compares names ignoring case and a message id is case-sensitive. The numbered tables (the seal, the settings changes, the tool calls, the deliveries) get their numbers 1, 2, 3 ...
from a counter record, so a number is taken back with the transaction that took it, as SQLite's are.

## How a value goes in and comes out

* **A moment** is stored as the wall clock of the site's time zone (System Settings), in a Datetime column, so that the Desk shows and filters it the way people read it. It comes back as the
  engine writes it: UTC text with `+00:00`. What the engine wrote comes back byte for byte; a moment that arrives with another offset comes back as the same moment in UTC. A wall clock cannot
  say which pass of the hour that happens twice when summer time ends a moment belongs to, so the first pass is chosen (the later pass reads back an hour early); the seal keeps its own time as
  exact text so that a chain never fails on a conversion. Pinned in `ai_munimji/tests/test_store_round_trips.py`.
* **The engine's JSON text** is kept in a JSON field byte for byte (key order, spaces, any language, two megabytes). The database refuses text that is not JSON there.
* **A number that may be empty** is a number plus a note of which were empty, because Frappe stores an empty number as 0 (measured, docs/STORE_PROBES.md); `None` and `0.0` come back as two things.
* **A value longer than 140 characters** in a short column is refused where the column is the record; the copies the json-row tables keep to find rows are cut, and the exact value stays in the row.
* **Links** (item, warehouse, supplier, order) are Link fields, so the Desk shows them as links, a User Permission on a warehouse hides the requests of other warehouses (shown over HTTP in
  `dev/scripts/permissions_http.py`), and renaming an item updates them. The engine's ids need not exist in ERPNext: the link is a pointer, not a promise. The cost is that ERPNext will not
  delete an item that a request still points at until the request is gone.

## Who may change them, and how

* The permission rows above decide who may read and write, and **a record is saved or deleted only by a document the stores made** (`ai_munimji/stores/record.py`). Without that, an Approver, who
  holds the right to write a request, could change its status with a plain API call (`PUT /api/resource/...`), with no engine rule and no seal behind it. With it, that call, creating a request
  by hand, deleting one and `frappe.client.set_value` are all refused for every role (417 or 403), over HTTP, tested.
* The stores read with `frappe.get_list` and documents, and write through documents, as the person who is signed in. There is no `get_all`, no `ignore_permissions` and no raw query in them;
  two modules are named exceptions, with the reason, in `tests/test_rules.py` (`unit.py`, the savepoint; `locks.py`, row locks). The scheduled job's mode (`frappe_core_stores(system=True)`) is
  Administrator only and is built in `jobs.py` only; it is the only mode that may append to the seal.
* **The audit seal** is append only for every role (even System Manager's row is read only), the controller refuses a change or a delete from anyone who gets past the rows (Administrator,
  `ignore_permissions`, `force`), and the database refuses a second entry that follows the same previous hash, so the chain cannot fork. What no controller can stop (a write that does not go
  through a document: SQL, `frappe.db.set_value`) is found by `AuditChain.verify`: a changed or deleted request, a changed settings record, an edited or removed seal row are each reported.
  The chain over a known history is the same four hashes in the same order as on SQLite (`AUDIT_GOLDEN`). A person's answer is sealed by the next run of the job, not at the instant of the
  answer, because a person's session never holds the right to append.

## Locks

* **Making a document from a request** takes a row lock (one record per document type: Purchase Order, Material Request, Stock Entry) until the transaction ends, then looks for an order of the
  same reference with a locking read. Two presses on two real database connections make one order; five make one. The file lock the client had first did not hold even on one server (it was
  released before the first press committed): with it two presses made two orders and five made five. Each part is shown to be needed: without the lock, or with the lock but a plain read
  (MariaDB's REPEATABLE READ does not show a connection what another committed after its first read), two orders are made. `ai_munimji/tests/world/test_parallel_presses.py`.
* **The scheduled job** takes a lease first (a record holding who and until when, so that a worker that dies gives it up when its time runs out). Two ticks at once make one proposal; with the
  lease taken away they make two. `ai_munimji/tests/world/test_end_to_end.py`.
* Found on the way, and why the locks are what they are: a lock record made on demand deadlocks when five presses arrive (each holds a shared lock on the duplicate and asks for the exclusive
  one); a locking read of a reference that has no order yet takes a gap lock that two different references' inserts then wait on. So the records are made at install and migrate
  (`ai_munimji.install.make_locks`), and one record serves a whole document type. Making an order is something a person does a few times a day; the cost is that two orders made at the same
  moment queue for the length of one request.

## Where the DocType stores differ from SQLite

None of the 60 shared checks differs. These are the places where an answer is not what SQLite gives, each a test in `ai_munimji/tests/test_store_round_trips.py`:

| What | SQLite | DocTypes | Right? |
|---|---|---|---|
| An item code, a supplier, an id typed in another case, or with an accent | a different value | the same value | yes for an item and a supplier: ERPNext treats them so. For an id: two ids that differ only in case collide; the engine's ids are lowercase hex, and a message id is named by a hash for this reason |
| A moment with another offset | comes back as written | comes back as the same moment in UTC | yes: the engine only ever writes UTC |
| The hour that happens twice at the end of summer time | exact | the first pass | a wall clock cannot say; the only moment affected is a request made in that hour on a site with summer time |
| Text that is not JSON in a JSON column | accepted | refused | yes: the column is documented as JSON |
| A short column (kind, status, ids ...) longer than 140 characters | accepted | refused | yes |
| A name longer than 140 characters, with leading or trailing space, or with `<` or `>` | accepted | refused | yes: a record cannot be named so |
| Search of the requests (`ApprovalStore.search`) | scans the table | narrows by every term in a text copy kept for the purpose, then applies the engine's exact rules | same answers; a search over very many requests is a Phase 5 question |

## The checks

| Implementation | The 60 store checks | The seal over the known history | Where it runs |
|---|---|---|---|
| SQLite | 60 of 60 | the golden chain | `erpnext-ai-agents`, `tests/test_store_contracts.py`, `tests/test_audit_golden.py` |
| In memory | 60 of 60 | the golden chain | the same |
| DocTypes | 60 of 60 | the golden chain, and `verify()` identical | this repository, `ai_munimji/tests/test_stores_contract.py`, `test_audit_seal.py`, on a bench |

Besides these: the permission rows of all 26 DocTypes of the app are pinned by a literal table and read three ways (the files, the synced rows, and Frappe's own answer for six kinds of
person on every DocType), `dev/permissions-http.ps1` asks the running site as five real people (list view, form, REST, guessed names, changes, a User Permission), and the whole way from the
stock to a draft Purchase Order is one test on real data (`tests/world/test_end_to_end.py`).

## Volume and retention

`ai_munimji/retention.py` (once a day by the scheduler, while Keep logs for (days) is a positive number; by hand with `bench --site <site> execute ai_munimji.retention.clean_up`) deletes what has served its purpose and what no person answers: runs, tool calls and the chat log older
than **Keep logs for (days)** on the settings page (90 by default; 0 keeps them), task records and vendor messages and replies after a year (never a task still running or an open
conversation), assistant answers after half a year, the ids of handled messages after a fortnight, and clears the trace of old tasks. It never touches a request, a proposal, an alert, a notice, a
work order, a transfer or anything else a person looks at or answers, whatever its age, and never the audit seal; a test fails if one of those tables is on its list or loses a record. With
0 the daily job is stopped and nothing is cleaned up by itself.
