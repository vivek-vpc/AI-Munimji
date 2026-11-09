# Changelog

What changed in the app for someone who installs it or builds on it. AI Munimji is not released and is not on the Frappe Marketplace; nothing below has been shipped to anyone.

## Unreleased

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
