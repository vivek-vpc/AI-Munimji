# Known limitations of version 0.1

AI Munimji is **not released**; these are the limits of the source as it stands. Each one is either tested to fail in a clear way, or is a fact about what ERPNext lets a person read.

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
* **A request a person starts and a scheduled run can still meet.** The job takes a lease, so two runs make one proposal; a request that a person starts by hand does not take it, so
  that person and a run, at the same moment, for the same item, could make two proposals. Nothing is ordered by either; the second is answered or dismissed like any other.
* **The hour that happens twice** when summer time ends: a record made in the second pass of that hour on a site with summer time reads back an hour early ([STORES.md](STORES.md)).
* **An item that a request points at cannot be deleted** in ERPNext until the request is gone (the Link field); renaming an item updates the requests.
* **The follow-up stores** (messages to vendors and their replies, delivery chases, receipt checks, quote rounds, stock transfers, cycle counts, the assistant's answers and chat log) have
  their DocTypes, their tests and their permissions, but the rules that use them are not part of version 0.1, so nothing writes to them yet and no screen shows them.
* **The Desk screens and the real schedule are not built.** The request form has one button (a draft Purchase Order for a purchase request); the approval form with the reasoning, the inbox,
  notifications and the job's own schedule are the next phase. The clean-up of old logs exists and is run by hand.
* **Searching the requests** narrows them in the database and then applies the engine's rules to what is left; over many thousands of requests that is slower than SQLite's scan.

## Taxes

* Reading **Tax Rules needs the Accounts Manager role**; a Purchase User does not have it, and the app adds no permission rows to ERPNext. The scheduled job runs as Administrator, reads the tax setup, and keeps the figures with the request. A person who changes the quantity or the vendor gets a recalculation from those kept figures.
* A request that a **person** starts (not the scheduled job) has no kept figures. If that person cannot read Tax Rules, the request says in plain words that taxes are not included, and every total in it is before tax. It never shows a zero tax as if it were a result.
* If the ERP has **no Tax Rule and no default purchase taxes template** for a supplier, the request says so, in different words from the case above: there, nothing is wrong with the reading, ERPNext simply applies no tax.
* Figures that were kept stay as they were when the request was made. If somebody changes the tax setup in ERPNext afterwards, a request that is already waiting does not follow the change; ask for the order again to read the new setup.
