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

## Taxes

* Reading **Tax Rules needs the Accounts Manager role**; a Purchase User does not have it, and the app adds no permission rows to ERPNext. The scheduled job runs as Administrator, reads the tax setup, and keeps the figures with the request. A person who changes the quantity or the vendor gets a recalculation from those kept figures.
* A request that a **person** starts (not the scheduled job) has no kept figures. If that person cannot read Tax Rules, the request says in plain words that taxes are not included, and every total in it is before tax. It never shows a zero tax as if it were a result.
* If the ERP has **no Tax Rule and no default purchase taxes template** for a supplier, the request says so, in different words from the case above: there, nothing is wrong with the reading, ERPNext simply applies no tax.
* Figures that were kept stay as they were when the request was made. If somebody changes the tax setup in ERPNext afterwards, a request that is already waiting does not follow the change; ask for the order again to read the new setup.
