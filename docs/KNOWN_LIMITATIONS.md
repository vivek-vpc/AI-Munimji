# Known limitations of version 0.1

These are the limits of version 0.1.1 as it stands. Each one is either tested to fail in a clear way, or is a fact about what ERPNext lets a person read.

## What the ERP client does not do yet

The rules in `ai-munimji-engine` ask the ERP through one interface (the "port"). `ai_munimji/erp_client.py` answers 16 of the port's 23 methods from the site's own data, in process, as the person who is signed in. The other seven are **left out of version 0.1**. Each raises `NotSupportedInThisVersion` ("… is not supported in this version of AI Munimji."), one test per method (`ai_munimji/tests/world/test_not_supported.py`), so a feature that needs one fails in plain words and never returns a made-up answer.

| Method | What it would read or do | Why it is left out |
|---|---|---|
| `get_receipt_lines` | Goods receipt lines, to check deliveries and invoices | The delivery and invoice checks are not part of version 0.1 |
| `get_stock_counts` | Stock counts (Stock Reconciliation), to plan cycle counts | Cycle counts are not part of version 0.1 |
| `get_stock_values` | The value of the stock on hand, to find slow stock | The slow-stock report is not part of version 0.1 |
| `last_purchase_dates` | When each item was last bought, for the same report | As above |
| `get_item_alternatives` | Item Alternative records, to suggest a substitute | Substitutes are not part of version 0.1 |
| `get_supplier_contact` | A supplier's e-mail and phone | Personal data; only needed to write to a supplier, which version 0.1 does not do |
| `send_email` | Sending a message | Version 0.1 sends nothing out of the site |

`get_documents` reads Purchase Order, Material Request and Purchase Receipt (the documents the stock rules look at). Asked for any other DocType it raises the same error.

## Where the app keeps its records

The engine's records are DocTypes ([STORES.md](STORES.md)). What that means in practice:

* **A person's answer is sealed by the next run of the job**, not at the instant of the answer (the standalone service seals at once). A person's session never holds the right to append to
  the audit seal. Until the run, `verify` reports the answer as "not sealed yet".
* **Orders made through the app queue.** Making a document from a request takes one row lock per document type until the request ends, so two orders made at the same moment wait for each
  other for the length of one request. Two presses of one button, on any number of workers or servers, make one order.
* **The locks need MariaDB's `innodb_snapshot_isolation` OFF** ([INSTALL.md](INSTALL.md)), as Frappe's own deployments have it. With it ON, work that overlaps in time fails with MariaDB error 1020 (a press says
  that another press is being handled, a run of the job records an error); nothing is ordered twice, but the second press or run does not wait its turn. The app cannot change the server: it warns
  after install and migrate and at the top of the Settings page while the setting is ON, and a refused answer reads one plain sentence; `ai_munimji.tests.test_database_setting` and the CI check it too.
* **A request a person starts and a scheduled run can still meet.** The job takes a lease, so two runs make one proposal; a request that a person starts by hand does not take it, so
  that person and a run, at the same moment, for the same item, could make two proposals. Nothing is ordered by either; the second is answered or dismissed like any other.
* **The hour that happens twice** when summer time ends: a record made in the second pass of that hour on a site with summer time reads back an hour early ([STORES.md](STORES.md)).
* **An Item, Warehouse, Supplier or Purchase Order that a record points at can be deleted** in ERPNext: the app's records are history and keep the name as text (`ignore_links_on_delete` in
  `hooks.py`). Renaming one updates the records. A fallback supplier that the Settings page still names is not deleted.
* **The follow-up stores** (messages to vendors and their replies, delivery chases, receipt checks, quote rounds, stock transfers, cycle counts, the assistant's answers and chat log) have
  their DocTypes, their tests and their permissions, but the rules that use them are not part of version 0.1, so nothing writes to them yet and no screen shows them.
* **Deferred on purpose, not built in version 0.1:**
  * a **dry run** (see what the check would do, without making anything);
  * a **stock monitor view** (a report of every item and why it is or is not low);
  * an **inbox** beyond the standard list view of Munimji Approval Request: the AI Munimji home page is shortcuts to the standard lists, with a count on three of them (no charts, no dashboard);
  * **reminders and expiry**: a request waits until someone answers it; none is reminded or closed by the clock, though the records carry the columns for it;
  * **e-mail notifications**: the one notification is in the Desk bell, to the role Munimji Approver, once per request; a request that is changed is a new request and is announced again;
  * a **volume test** of the stores with many thousands of records;
  * **sealing at the moment of the answer**: the job seals what was answered at its next run (above).

  The clean-up of old logs runs once a day while "Keep logs for (days)" is a positive number. With 0 it does not run, so nothing is cleaned up by itself, the records with a fixed period (task records, vendor messages, the ids of handled messages) included; it can still be run by hand.
* **Searching the requests** narrows them in the database and then applies the engine's rules to what is left; over many thousands of requests that is slower than SQLite's scan.

## The stock check on a large site

The numbers are in [SCALE_MEASUREMENTS.md](SCALE_MEASUREMENTS.md): a site of 30,000 items and 5 million stock ledger entries. What to know:

* **A run works in batches of 200 items and commits after each.** It reads and analyses the items first (which writes nothing, so it holds no lock), then raises the requests, worst first; while it raises requests
  (and, later, proposals) a batch is also ended after half a second, whatever it has done by then. At the end of every batch it commits, renews its lease and writes how far it has got in its Job Run (`Munimji Job Run`, "How far it got"). So a person who answers a request the run is replacing waits for the batch under way, not for
  the whole run; a failure takes back one batch, and the run, started again, acts on each item once (the alerts it already raised are found, not raised again).
* **The run is queued on the long queue with a timeout of six hours**, not run by the scheduler's own queue, which ends a job after 300 seconds. Your site needs a worker for the `long` queue (Frappe's own
  setup has one). A run that is queued or running is not queued a second time, and the lease keeps two runs from working at once. A run whose lease was taken by another stops, and says so in the log.
* **Memory grows with the number of items**: a run keeps the figures of each item that needs a request, and four numbers for each item whose stock is fine, until it has been through all of them.
* **The first run after the cache is cleared reads the whole ledger once**: an item's first stock movement (which can make its history start earlier than its creation) is looked up once and kept in Frappe's cache,
  for items created within the last 1,100 days. A ledger entry that is back-dated before an item's first one is noticed only after `bench clear-cache`.
* **A schedule that can start the check less than 15 minutes after the last start is refused** on the Settings page, with a sentence saying so. Every check reads all the stock. A page saved by an earlier version
  with such a schedule is not followed: the job runs at the default time (0 6 * * *) and the log says so, until someone saves a schedule the page accepts.
* **The audit sweep seals at most 500 requests and 500 settings changes at a time**, and a run sweeps up to 50 times, so a backlog is cleared over several runs and a sweep with nothing new reads a handful of rows.
  A request carries the flag `sealed` (the app's own column) once its entry is in the chain; a site restored from a backup that predates the flag is put right by the first sweeps, and nothing is sealed twice.
* **The daily clean-up of the logs removes at most 5,000 records a run, oldest first, in batches of 100 with a commit after each**, so a first backlog is cleared over several days instead of failing every day. Frappe queues one background job for every document that is deleted and refuses to queue more than `max_queued_jobs` (500 by default), so the clean-up waits (up to 30 seconds) for your workers to take the jobs of the last batches, and ends its run if they have not: it goes on at the next run. A site whose workers are always busy clears a backlog slowly, and says nothing.

## Taxes

* Reading **Tax Rules needs the Accounts Manager role**; a Purchase User does not have it, and the app adds no permission rows to ERPNext. The scheduled job runs as Administrator, reads the tax setup, and keeps the figures with the request. A person who changes the quantity or the vendor gets a recalculation from those kept figures.
* A request that a **person** starts (not the scheduled job) has no kept figures. If that person cannot read Tax Rules, the request says in plain words that taxes are not included, and every total in it is before tax. It never shows a zero tax as if it were a result.
* If the ERP has **no Tax Rule and no default purchase taxes template** for a supplier, the request says so, in different words from the case above: there, nothing is wrong with the reading, ERPNext simply applies no tax.
* Figures that were kept stay as they were when the request was made. If somebody changes the tax setup in ERPNext afterwards, a request that is already waiting does not follow the change; ask for the order again to read the new setup.
