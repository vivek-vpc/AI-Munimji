# Changelog

What changed in the app for someone who installs it or builds on it. 0.1.0 (9 Nov 2026) was the first version; it was made but not tagged or submitted, and 0.1.1 is the version to install. The entries under 0.1.0 are how it was built up, phase by phase.

## Unreleased

### Fixed after the production-readiness review: scale and concurrency

Measured on a site of 30,000 items and 5.3 million stock ledger entries; the numbers, the method and the tools to repeat it are in `docs/SCALE_MEASUREMENTS.md`. The stock check needs `ai-munimji-engine` 0.1.2
(batches and `get_items`); `pyproject.toml` pins 0.1.2.

* **The stock check no longer is one transaction for the whole site.** It works through the items in batches of 200 and, after each batch, commits, renews its lease and writes how far it has got in its Job Run
  (new column "How far it got"). Before, every record it changed stayed row-locked for the whole run, so a person answering a request the run had touched waited until the run ended or was told "busy" (at 30,000 items
  the run took 9 minutes and 12 of 20 answers waited the database's whole 50 seconds and failed); a failure near the end threw everything away; and a run longer than the scheduler's 300 seconds never completed. Now the
  scheduled entry (`jobs.check_stock`) queues the run on the long queue with a timeout of six hours; a run that dies half way keeps the batches before it, and run again raises each request once; a run whose
  lease another run has taken stops. Its memory no longer holds every item's whole analysis.
* **The stock ledger is read for what is asked, not for everything.** `get_consumption` lets the database add up each item's movements of a day; an item's first movement is looked up for the items that need it, once,
  and kept in Frappe's cache (it was a GROUP BY over the whole ledger on every run and on every answer to a reorder request); one item is read without listing all of them (`get_items`).
* **The audit sweep costs what is new.** A closed request and a settings change carry the flag `sealed` (new, the app's own column), set when their entry is appended; the sweep asks for those that do not, 500 at a time,
  and a run sweeps up to 50 times. With 200,000 sealed requests and nothing new it read 400,001 rows in 8 to 11 seconds; it now reads 1 to 3 rows. A patch sets the flag on a site sealed before it; a site where it
  is missing is put right by the sweeps themselves, and nothing is sealed twice.
* **The clean-up of the logs makes progress.** It removes at most 5,000 records a run, oldest first, in batches of 100 with a commit after each, and only as fast as the workers take the background job that Frappe queues for
  every deleted document (it waits up to 30 seconds for room, and ends its run if there is none). A backlog of 150,000 would have taken 104 minutes in one transaction, past the job's time limit, and rolled back every day.
* **A schedule that can start the check less than 15 minutes after the last start is refused** on the Settings page, with a sentence that says so; one saved by an earlier version is not followed (the job runs at
  the default time and the log says so).

### Added after the production-readiness review: the flow a person can follow

From the use of the app: after approving a "Reorder suggested" request nothing visible happened until the next scheduled check, the person was not told what to do next, and the draft Purchase Order's number was not shown anywhere. The stock check needs `ai-munimji-engine` 0.1.2 (`ProcurementAgent.run(work_orders=)`, with the batch parameters above); `pyproject.toml` pins 0.1.2.

* **The vendors are compared within about a minute of approving a reorder.** The answer queues a job (long queue, after the commit) that compares the vendors for that one reorder, as Administrator, under the stock check's lease; the purchase request appears in Munimji Approval Request. If the job cannot take the lease, the next scheduled check does it, and no reorder gets two purchase requests. (`hand_off.py`, `jobs.run_vendor_comparison`)
* **Every answer is followed by one plain sentence** saying what happens next and where to look: "Approved. The vendors are being compared; the purchase request will appear in Munimji Approval Request in about a minute.", "Draft Purchase Order PO-... made. Review and submit it in ERPNext." (the number is a link), "Closed. Nothing was ordered." (`next_step.py`)
* **A Flow block on every request** of the flow: Reorder request -> Purchase request -> Draft Purchase Order, each step a link, the request on the screen marked, a changed request showing what replaced it, and the draft order's number kept on the approved request. An item with no vendor history says that no comparison was possible and to order it in ERPNext by hand, then press "Got it". (`flow.py`, `api.flow`)
* **A "Run the check now" button on AI Munimji Settings** for Munimji Managers and System Managers: it queues the stock check, refuses a second press while one is queued or running, and the page shows when the last check ran, how far it got and how many requests it made (new column "Requests it made" on the Job Run; `bench migrate` adds it). (`api.run_check_now`, `api.check_status`)
* **A "How a request flows" section** on the Settings page, in the user guide and in the listing text.
* **No pop-up of "not found" lines after pressing Approve.** Asking Frappe for a record that is not there (most settings overrides are not set) also put "Munimji Settings Override ... not found" among the messages
  the browser shows with the reply, five times over, on top of the new sentence. The stores now take that message back (`stores/missing.py`). Found while following the flow in the browser.
* **Following it yourself:** `dev\demo.ps1` puts a small demo supply chain on the development site (one item bought from three suppliers with different prices and delivery times, one late, with 90 days
  of usage; one item with no supplier) and prints the walkthrough; `-Run` walks through it in the container's headless browser as the manager and the approver and says how long each step took.

## 0.1.1 (10 Nov 2026)

### Added

* **AI Munimji is on the Desk.** Until now a person had to know to search for "Munimji Approval Request". The app now ships what Frappe 16.55 uses to put an app on the Desk: a **tile on the apps screen**
  (hook `add_to_apps_screen`, shown only to people with a Munimji role and to System Managers, with a small copy of the logo in `public/images/`), the app's **Dock** record (`dock/ai_munimji/`), a module
  **Sidebar** and a public **Workspace** page "AI Munimji" (`ai_munimji/sidebar/`, `ai_munimji/workspace/`). The home page has shortcuts to **Waiting for your answer** (with the count), **Stock alerts** (count),
  **Draft purchase orders** (count), **Answered requests**, **Expired or withdrawn**, **All requests** and **Settings**; the sidebar has the same lists, plus purchase proposals and stock transfers. Each person
  sees only the rows they may open (a viewer sees no Settings and no Purchase Orders). They are Frappe's own exported files, installed by `bench migrate`; uninstalling removes them (`tests/test_desk.py`, and the
  uninstall check counts them). It needs Frappe 16.55.2 or later, which `pyproject.toml` already requires.

### Fixed after review

* **A wrong answer no longer ends in a server error.** The parameters of an answer (`ai_munimji.api.answer`) that are not a JSON object (text that is not JSON, a list, a number, `null`) or are longer than 2,000
  characters are refused with the status `refused` and one plain sentence; nothing is read from them and nothing is changed. Before, `json.loads` raised, or the engine failed on a value that has no `.get`.
* **The Settings page says when items were skipped.** An item the engine cannot analyse is skipped so that the others are looked at; until now only the log knew. The stock check now counts them and keeps
  "N items could not be analysed" with its Job Run record, and the top of AI Munimji Settings shows it after the run, with the database warning and the "monitoring is off" note, not instead of either.
  The item codes are in the app's log and in the latest Munimji Agent Run.
* **A purchase return is not a delivery.** A Purchase Receipt with `is_return = 1` (goods sent back, negative quantity, the same purchase order) is left out of the receipt dates that give a vendor its lead time and
  on-time rate. Purchase Order has no `is_return` field in v16 (checked on 16.55.2), so the order history is not filtered, and nothing in the app reads a Purchase Invoice.
* **The logs are cleaned up every day.** The existing clean-up (`ai_munimji.retention.clean_up`) is a daily job (Scheduled Job Type on a Scheduler Event, so a migrate keeps it) that follows **Keep logs for (days)**:
  it runs while the number is positive (90 by default) and is stopped at 0. It still never touches a request, a proposal, an alert, a notice, a work order or the audit seal. `docs/PRIVACY.md`, `USER_GUIDE.md`,
  `KNOWN_LIMITATIONS.md`, `INSTALL.md` and `STORES.md` say so.
* **The engine fixes, with the engine 0.1.1 they are in.** Dates that overflowed for very large stock, prices that are not positive numbers, an on-time rate outside 0 to 1, decimal commas in a typed quantity,
  totals before tax next to totals with tax, and returns in the vendor scorecard are fixed in `ai-munimji-engine` 0.1.1 (the engine's changelog says how). The app pins it exactly, `ai-munimji-engine==0.1.1`
  in `pyproject.toml`, so it installs only once 0.1.1 is on PyPI. 0.1.0 of the engine is on PyPI and has none of these fixes.
* **Version 0.1.1.** `__version__`, the README, `docs/INSTALL.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/LISTING.md` (the registry file's `version`) and `docs/RELEASE_CHECKLIST.md` name it.

## 0.1.0 (9 Nov 2026)

### The release commit

* **Version 0.1.0.** `__version__`, the descriptions in `hooks.py` and `pyproject.toml` (the same sentence as the listing's summary), and the wording of the README, `docs/INSTALL.md` and `docs/KNOWN_LIMITATIONS.md` no longer say
  that the app is in development.
* **The engine is pinned exactly:** `ai-munimji-engine==0.1.0` in `pyproject.toml`, and it is on PyPI (published on 9 Nov 2026 from the tag `engine-v0.1.0` of the `erpnext-ai-agents` repository). CI installs it from there,
  at the pin that `pyproject.toml` holds; the build of the engine from the other repository, and the variables `ENGINE_REF` and `ENGINE_REPO` that steered it, are gone.
* **The pages are in `docs/`:** `PRIVACY.md`, `TERMS.md`, `SUPPORT.md`, `USER_GUIDE.md` (reworded after the app was compared with them: seven custom fields, a change or cancel of an order is said, two answers from low stock to an order,
  the seal waits for the next run) and `LISTING.md` (the fields of the registry entry); the logo is `docs/img/ai-munimji-logo.png`. The test of the public text no longer needs an exception.

### Phase 6: checks a Marketplace review would care about

* **The database setting.** After install and migrate the app prints and logs a warning if MariaDB has `innodb_snapshot_isolation` ON, and AI Munimji Settings shows the same warning in red at the top
  while it is ON; a database that cannot be asked says nothing. The statement is one fixed, read-only `SHOW VARIABLES` in `dbcheck.py`, the only raw SQL the rules test allows. A person whose answer lost to
  another one given at the same moment now reads one plain sentence (status `busy`) instead of the database's words or the engine's bare "Status: pending."
* **Nothing leaves the site, proved.** A static test (no import of a network, mail or model library, no call of Frappe's mail or request functions, no outside address in the scripts) and a runtime test (the
  scheduled job and the whole approval flow with outside connections, HTTP and mail cut off). The form no longer adds "Taxes are not included in these totals." to a request whose engine note already says why
  there are no tax figures.
* **Versions.** The lower bounds in `[tool.bench.frappe-dependencies]` are the oldest versions CI ran on (Frappe 16.55.2, ERPNext 16.54.0), which are also the newest stable v16 tags. `pyproject.toml` now declares the licence.
* **Public-repository hygiene.** `SECURITY.md`; the four public pages (`docs/PRIVACY.md`, `TERMS.md`, `SUPPORT.md`, `USER_GUIDE.md`) as drafted; `docs/BACKUP_RESTORE.md` (a rehearsed backup and restore, with
  `dev/scripts/check_restore.py`); `docs/RELEASE_CHECKLIST.md`.

### Phase 5: the flow a person can use

* **The stock check runs on a schedule that the Settings page sets.** Watch stock switches the job on and off (off until a person ticks it) and "Check stock at" is its time. The job is a Scheduled
  Job Type on a Scheduler Event, made at install and at every migrate, so that `bench migrate` does not reset or delete a schedule a person has edited; the placeholder cron entry of `hooks.py`
  (every 5 minutes, always on) is gone. A Munimji Manager may save the page without holding any right on Frappe's job records: `schedule.py` is the one module besides the install hooks that writes
  with `ignore_permissions` (`tests/test_rules.py` names it). The page now says what to review before switching it on.
* **The approval form** shows a request in words, drawn from the JSON the engine stored (nothing is worked out again): the stock and how long it lasts, what is proposed and what it costs, when it
  arrives, why this vendor, the other vendors and why they were not chosen, the duties and taxes or the plain statement that taxes are not included, and what each button does. Buttons: Approve,
  Change quantity, Change vendor, Dismiss (and Got it, for a request that asks for no order). The first answer wins; the second is told who answered first. `ai_munimji.api.answer` also returns the
  revised request to open after a change and the vendors to choose from.
* **One notification** in the Desk bell of each person with the role Munimji Approver when a request is made, once per request, not per tick; no e-mail. Made if missing, never overwritten.
* **An Item, Warehouse, Supplier, Purchase Order or Stock Entry that a record points at can be deleted** (`ignore_links_on_delete`); the record keeps the name as text. Before this the Link fields stopped ERPNext
  from deleting them.
* Agent Run keeps its create-only right for Approver and Manager; a test shows that nobody can put another user's name on the row.
* The placeholder form's single "Create Purchase Order" button is replaced by the form above; no data changes.

### Phase 4b: the engine's records are DocTypes

* **25 DocTypes hold the engine's records** (requests, purchase proposals, alerts and notices, work orders, transfers, chases, the audit seal, the agents' log and the rest); the table, the
  rights of each role, how a value is kept, the locks and the differences from SQLite are in [docs/STORES.md](docs/STORES.md). The engine's 60 shared store checks pass on them next to
  SQLite and memory.
* **Munimji Approval Request is the engine's approval record now.** Its placeholder fields from the first experiment (a Select status of Pending / Ordered / Rejected, a link to the draft order,
  a free-text reason) are gone. **There is no patch to move old values, because no earlier version was released**: no site holds a request made with the old fields except a development site, and
  a development site is rebuilt. (Frappe never drops a column, so a database that had the old fields keeps their empty columns; the uninstall notes say the same of every column the app adds.)
* **Two presses of one button on two database connections make one order.** The file lock the ERP client had first did not hold even on one server; it is replaced by a row lock and a locking read.
  This needs MariaDB with `innodb_snapshot_isolation = OFF`, as Frappe's own Docker files run it ([docs/INSTALL.md](docs/INSTALL.md)); the first run on GitHub used the stock image (ON) and failed 6 of the 10
  overlapping-work tests, which is how it was found. CI now sets it, and a test says what is wrong when it is not.
* **The audit seal is append only for every role**, is the same chain as the standalone service's (a known history gives the same four hashes), and a tampered record is found.
* **The app's records are changed by the app only** (a plain API call that edits a request's status is refused for every role).
* **The scheduled job runs the engine's stock check**: it reads in the system mode, proposes, and takes a lease so that two runs make one proposal. Watch stock stays off by default.
* **A clean-up of old logs** and the setting "Keep logs for (days)" (90 by default; 0 keeps them).
* The people of the tests hold the Munimji role that goes with their job; a person with an ERPNext role and none of the Munimji roles sees none of the app's records.

### Earlier phases

* Phase 4a: the ERP client that answers the engine's stock port from the site's own data, as the person who is signed in (16 of the port's 23 methods; seven are left out and say so).
* Phase 3: the app (settings, roles, the standalone service's custom fields, a tested uninstall).
