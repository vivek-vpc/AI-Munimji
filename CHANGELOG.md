# Changelog

What changed in the app for someone who installs it or builds on it. AI Munimji is not released and is not on the Frappe Marketplace; nothing below has been shipped to anyone.

## Unreleased

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
  a free-text reason) are gone. **There is no patch to move old values, because nothing was released**: no site holds a request made with the old fields except a development site, and
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
