# Installing AI Munimji, and who needs which role

These notes are for version **0.1.1** of AI Munimji, for people who install it from the source on their own bench. It has been run only on **Frappe 16.55.2 and ERPNext 16.54.0** (version 16 of both; no other major version has been tried; earlier checks were on ERPNext 16.53.0, and the permission results below were measured again on 16.54.0 and are the same).

## What you need first

* A bench with Frappe 16 and ERPNext 16 and a site with ERPNext installed (`required_apps` in `hooks.py` says ERPNext is a must).
* **MariaDB with `innodb_snapshot_isolation = OFF`.** Frappe's own Docker files (frappe_docker) and its Pilot start MariaDB 11.8 this way; the stock MariaDB 11.8 image has it ON. With it ON a locking read of a row that another connection changed since the transaction began fails with error 1020 ("Record has changed since last read"), so two presses of one button, or two runs of the job at the same moment, fail instead of waiting (the app's parallel tests fail 6 of 10, measured on 9 Nov 2026). Everything that does not run at the same moment works either way. Set it in the server's `[mysqld]` section; on a running server `SET GLOBAL innodb_snapshot_isolation=OFF` is read by new connections. `ai_munimji.tests.test_database_setting` checks it and says this when it is wrong.
* **The app cannot change the server, so it says so:** after install and migrate it prints and logs a warning if the setting is ON, AI Munimji Settings shows the same warning in red at the top while it is ON, and a person whose answer lost to another one given at the same moment reads one plain sentence (nothing is ordered twice). A database that cannot be asked says nothing.
* The rules package, `ai-munimji-engine`, comes from PyPI: installing the app installs the exact version it pins. (To try an engine that is not published, put a local wheel of it into the bench's Python environment first: see the README, "The engine".)

```
bench get-app <the folder of this repository>
bench --site <your site> install-app ai_munimji
```

## What installing adds to your site

| What | Where |
|---|---|
| Three roles: Munimji Viewer, Munimji Approver, Munimji Manager | Role |
| AI Munimji on the Desk: a tile on the apps screen (shown to people with a Munimji role and to System Managers), a sidebar, and a home page of shortcuts to the lists that need attention (requests waiting for an answer, stock alerts, draft purchase orders, past requests, Settings), each with a count where that helps. Each person sees only the rows they may open | Dock, Sidebar, Workspace |
| The page AI Munimji Settings (in the AI Munimji sidebar, or search "AI Munimji Settings"), with a calendar table | Single DocType |
| The list Munimji Approval Request, and 24 more DocTypes that hold the engine's records: purchase proposals, stock alerts and notices, work orders, the audit seal, the agents' log, locks and the rest (table: [STORES.md](STORES.md)) | DocType |
| An "approve" permission for that list | Permission Type |
| Seven read-only fields that carry the request's reference and who approved: `custom_agent_ref` and `custom_agent_approved_by` on Purchase Order, Material Request and Stock Entry, and `custom_agent_note` on Material Request | Custom Field |
| The stock check's scheduled job: stopped until Watch stock is ticked, then run at the time of "Check stock at" on the Settings page (ERPNext's scheduler runs a job every 4 minutes at the soonest). It hangs on a Scheduler Event, which is what keeps `bench migrate` from resetting or deleting it | Scheduler Event, Scheduled Job Type |
| A notification to the people with the role Munimji Approver, in the Desk bell, when a request is made (no e-mail). Made if missing at install and migrate, never overwritten: switch it off or edit it as you like | Notification |

The app adds **no permission rows to any ERPNext DocType**. What a person may see or do in ERPNext is decided by ERPNext's own roles, and the Munimji roles decide only what they may do with the app's own pages.

## Who needs which role

| A person who... | Munimji role | ERPNext roles they also need |
|---|---|---|
| looks at the requests | Munimji Viewer | **Stock User**, to see the stock the requests are about (Item, Bin, Stock Ledger Entry, Warehouse) |
| answers a request, which makes a **draft** Purchase Order under their own login | Munimji Approver | **Stock User** to read stock, and **Purchase User** to create the draft: measured on ERPNext 16.53.0 and again on 16.54.0, Purchase User is enough to create a Purchase Order; on 16.54.0 it is also enough to change the quantity of an order made from a request and to cancel it (a Purchase Manager adds nothing, and cannot replace Purchase User). (The standalone service's list of roles is wider; that is a matter of its service account, not of the people who use this app.) |
| changes the settings, and may delete requests | Munimji Manager | the same as an approver if they also answer requests |
| everything | System Manager | none |

A person with only a Munimji role reads nothing of ERPNext's (no Item, Bin, Stock Ledger Entry or Purchase Order). That is intended. A person with an ERPNext role and none of the Munimji roles sees none of the app's records: the Munimji roles are what open them. What each role may do to each of the app's records is the table in [STORES.md](STORES.md), pinned by `ai_munimji/tests/test_permissions.py`.

The app's records are changed by the app only, whatever a person's rights: an Approver answers a request through the app, not by editing its status, and the audit seal is appended to by the scheduled job alone.

Approving needs two things at once: the Munimji "approve" right, and the right to create a Purchase Order in ERPNext. Someone who has one without the other is refused, and nothing is created.

### What each kind of person gets from the ERP client

The part of the app that reads stock and purchases (`ai_munimji/erp_client.py`) works as the person who is signed in. It never reads with more rights than they have, and it never submits a document. Measured on the development site (`ai_munimji/tests/world/test_permissions.py` holds the table):

| Reads and writes | Stock User only | Purchase User + Stock User | Only a Munimji role |
|---|---|---|---|
| Items, warehouses, stock, usage, sales orders due, vendors and their prices, orders and requisitions already made | yes | yes | permission error |
| A vendor's credit days (payment terms) | not shown: unknown, not guessed | shown | permission error |
| Duties and taxes (Tax Rules) | permission error | permission error | permission error |
| Make a draft Purchase Order | refused | yes | refused |
| Make a draft Material Request or Stock Entry (transfer) | yes | yes | refused |
| Change the quantity of, or cancel, an order made from a request | refused | yes | refused |

A permission error means the person gets no rows, not an empty list. Someone who may only pick an item from a drop-down (the "select" right) is treated the same as someone who may not see it. Only two places in the app go around a person's rights: the scheduled job (it reads as Administrator) and the install and uninstall steps (they create and remove the app's own roles and fields). `ai_munimji/tests/test_rules.py` fails the build if any other place uses `ignore_permissions` or `get_all`.

### Taxes in a request

Reading **Tax Rules needs the Accounts Manager role**, which a Purchase User does not have, and the app adds no permission rows to ERPNext. So:

* The **scheduled job** runs as Administrator, reads the tax setup of each vendor, and keeps the figures it used with the request.
* When a person **changes the quantity** (or the vendor), the new totals are worked out from those kept figures, not from a fresh read as that person. If someone changes the tax setup in ERPNext afterwards, a request that is already waiting does not follow the change; ask for the order again to read the new setup.
* If **no tax figures are available at all** (for example a request a person started, who may not read Tax Rules), the request says in plain words: "Taxes are not included in these totals". Every figure in it is then before tax. A tax of zero is never shown as if it were a result.
* If ERPNext **has no Tax Rule and no default purchase taxes template** for the vendors, the request says that instead ("Duties and taxes are not in this comparison"): the read worked, and ERPNext applies none.

## Switching the stock monitor on

**After installing, the stock monitor is off.** Nothing creates requests for your stock until a person has looked at the thresholds and switched it on: open AI Munimji Settings, review the thresholds, the time in "Check stock at" and who holds the role Munimji Approver (they are told when a request is made), then tick Watch stock. Saving the page starts the scheduled job at that time; unticking it stops the job. While it is off the page says so at the top, and the scheduled job does nothing. (The standalone service starts with its monitor on; the app deliberately does not, see [NAMES.md](NAMES.md).)

## Settings

Open AI Munimji Settings as a Munimji Manager or System Manager. The values are checked by the same rules as the standalone service uses for its `settings.yaml`, so a value is accepted here exactly when the service accepts it there. The time zone is the one in System Settings. **Keep logs for (days)** says how long what the agents did and the chat log are kept: 90 by default. A clean-up (`ai_munimji.retention.clean_up`) runs once a day while this is a positive number and removes what is older; with 0 it does not run and every log is kept. It never deletes a request, a proposal, an alert or the audit seal. There are no secrets in version 0.1.

## Taking it out

See [UNINSTALL.md](UNINSTALL.md).
