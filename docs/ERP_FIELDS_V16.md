# What the ERP client reads in ERPNext 16, and where that differs from the standalone service

`ai_munimji/erp_client.py` answers the engine's stock port from the site's own tables. The standalone service answers the same port over HTTP (`erp_agents/core/erp/erpnext.py`, the "REST client"). This page lists the DocTypes and fields the Frappe client reads, says whether each exists in **ERPNext 16.54.0 on Frappe 16.55.2** (the development site), and lists every difference between the two clients.

## How this was checked

```
python dev/scripts/list_client_reads.py <erpnext.py of the standalone repository> ai_munimji/erp_client.py <folder>     # what each client's source reads (no site needed)
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/check_client_fields.py <folder>   # asks the site whether each field exists
```

The first script reads the source of both clients (50 distinct reads in the REST client, 34 in the Frappe client). The second asks `frappe.get_meta(doctype).has_field(...)` for every field either client names, in a select list or in a filter. **Result: every field exists**, with one filter form to explain (below). The Bin columns the client builds at run time come from the engine's `STOCK_COLUMNS`; all seven exist.

## What each method reads (Frappe client)

| Port method | DocTypes and fields | Needs the read right on |
|---|---|---|
| `healthcheck` | none (the site and its database are up) | nothing |
| `list_items` | Item: name, item_name, item_group, stock_uom, lead_time_days, creation; filtered on is_stock_item, disabled. Stock Ledger Entry: item_code, MIN(posting_date) (filtered on is_cancelled) for "first movement" | Item; the ledger is optional |
| `list_warehouses` | Warehouse: name, is_group, disabled | Warehouse |
| `get_stock` | Bin: item_code, warehouse, actual_qty, projected_qty and the seven columns of `STOCK_COLUMNS` (reserved_qty, reserved_qty_for_production, reserved_qty_for_sub_contract, reserved_qty_for_production_plan, ordered_qty, indented_qty, planned_qty). Warehouse (transit ones). Purchase Order and Purchase Order Item (name, status; item_code, qty, received_qty, schedule_date) for the next arrival | Bin; the rest is optional |
| `get_consumption` | Stock Ledger Entry: item_code, posting_date, actual_qty; filtered on voucher type (Delivery Note, Sales Invoice), the dates, is_cancelled | Stock Ledger Entry |
| `get_open_sales_orders` | Sales Order: name, status. Sales Order Item: parent, item_code, qty, delivered_qty, conversion_factor, delivery_date. No customer is read | Sales Order |
| `get_vendor_offers` | Purchase Order and Purchase Order Item (qty, rate, **base_rate**, schedule_date). Optional: Supplier (supplier_name, payment_terms, disabled, country), Item Supplier (supplier), Payment Terms Template Detail (credit_days), Purchase Receipt and Purchase Receipt Item (purchase_order, posting_date), Supplier Quotation and Supplier Quotation Item (qty, rate, base_rate, lead_time_days; valid_till, status) | Purchase Order; the rest is optional |
| `item_min_order_qty` | Item: min_order_qty | Item |
| `get_purchase_taxes` | Supplier (supplier_group, tax_category, country), **Tax Rule**, Purchase Taxes and Charges Template (the default one, and the chosen one as a document), Item and Item Tax Template (as documents) | **Tax Rule: Accounts Manager** |
| `get_documents` | Purchase Order, Material Request, Purchase Receipt and their item tables (see `DOC_SPECS`) | the DocType asked for |
| `find_by_reference` | the DocType asked for: name, custom_agent_approved_by; filtered on custom_agent_ref and docstatus < 2 | the DocType asked for |
| `create_purchase_order`, `create_material_request`, `create_stock_transfer` | Company (default_currency), Supplier (default_currency), Currency Exchange, Supplier Quotation, Purchase Taxes and Charges Template: read to fill the draft in. Writes a draft Purchase Order, Material Request, or Stock Entry (Material Transfer) | create on the document |
| `update_purchase_order_qty`, `cancel_purchase_order` | Purchase Order (as a document) | write / cancel / delete on it |

"Optional" means: when the person may not read that DocType, the figure it would have added is unknown and the answer says so (for example, a vendor's credit days are left empty for a Stock User); it is never guessed. Everything else raises `frappe.PermissionError`.

## Names that matter in version 16

* **Bin**: the reservation and ordering columns above are all present in 16.54.0, as are `actual_qty` and `projected_qty`.
* **Purchase Order Item.base_rate** and **Supplier Quotation Item.base_rate** exist: they are the price in company currency, the one the comparison uses; `rate` is in the document's own currency.
* **Tax Rule has no `disabled` flag** in 16.54.0. A rule is switched off by its `from_date` / `to_date` (and ignored if the document's date is outside them), which is how the tests end a rule. Its address fields (billing_city … shipping_country) and `item`, `item_group` cannot be judged without the order's own addresses, so both clients leave a rule that depends on them out and report it in a note ("Tax Rules not considered because they cannot be judged from here").
* **Payment terms**: `Supplier.payment_terms` names a Payment Terms Template; the credit days are on its child table, **Payment Terms Template Detail.credit_days**. A Stock User cannot read either.
* **Custom fields** the app adds (`custom_agent_ref`, `custom_agent_approved_by` on Purchase Order, Material Request and Stock Entry, `custom_agent_note` on Material Request) are the same fields, with the same names, that the standalone service's `erp-setup` makes, so the two can work on one site.
* `frappe.db.is_connected` does not exist in 16; the health check asks for `frappe.local.site` and a live `frappe.local.db` instead.
* A Stock Entry made without `posting_time` as a time (not a string) fails in `combine()`; the client sets it with `nowtime()`.

## Where the two clients differ

| Subject | REST client (standalone) | Frappe client | Why, and is it right |
|---|---|---|---|
| Who it acts as | one service account for everyone | the signed-in person | The point of the app. Results for a restricted person can differ; `ai_munimji/tests/world/test_permissions.py` pins who gets what. |
| Transport | `/api/resource` over HTTP, 1000 rows a page | `frappe.get_list(..., limit_page_length=0)` in process | Same rows; no paging to get wrong. |
| A DocType the person may not read | the service account can, so it never happens | `frappe.PermissionError`, never an empty list (a person with only the "select" right is refused too) | Correct: an empty list would look like "no stock". |
| Item minimum order quantity | reads the whole Item document and takes `min_order_qty` | reads only the `min_order_qty` column | Less data; the same number. |
| Company and supplier currency | reads the whole Company and Supplier documents | reads one column (`default_currency`) | As above. |
| Supplier read in `get_vendor_offers` | tries with `country`, falls back to a read without it | one read with `country`, optional as a whole | The fallback was for a service account without the field; a person's right to read Supplier is what matters here. |
| Tax Rule | reads Tax Rules with the service account's own rights, for every request | needs Accounts Manager; the scheduled job reads them as Administrator and keeps the figures with the request | See "Taxes in a request" in INSTALL.md. |
| Dates and numbers | JSON strings | `date`, `datetime`, `float` | Both clients convert to the same types before they answer (`to_date`). |
| Making a document | `POST /api/resource` as the service account; the approver goes in `custom_agent_approved_by` as "name via channel" | `frappe.get_doc(...).insert()` as the person, same two fields, never submitted; a lock named for the reference | Same result on the document; the owner of the document is now the person who approved. |
| Finding a duplicate | `custom_agent_ref` equal, docstatus < 2 | the same, and an empty reference looks for nothing (Frappe reads an empty filter value as "is empty", which would match every document made by hand) | The extra guard is deliberate and tested. |
| Parts left out | all of the port | 7 methods raise `NotSupportedInThisVersion` (KNOWN_LIMITATIONS.md) | Not part of version 0.1. |

**Read by the REST client only**: the receipts, invoices, stock counts, contacts and item alternatives that the seven left-out methods need (Purchase Receipt and Purchase Invoice details, Stock Reconciliation, Contact, Item Alternative, Bin.stock_value), and a whole Company, Supplier, Item document where the Frappe client asks for one column.
**Read by the Frappe client only**: the Item columns `disabled`, `is_stock_item` and `min_order_qty` and `Supplier.default_currency`, each as a column of a list (the REST client builds the same filters in a different form, or reads the whole document).

One filter form to explain: the REST client's contact lookup filters `Contact` on `["Dynamic Link", "link_name", "=", supplier]`. `Dynamic Link` is the name of Contact's child table, not a field of Contact, which is how Frappe filters a parent on a child table's field. It is valid in 16 and is used only by a method the Frappe client leaves out.
