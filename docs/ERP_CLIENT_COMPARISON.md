# The ERP client on three implementations of one port

The engine's stock rules ask the ERP through one interface (the "port"). Three things answer it: the **demo ERP** of the standalone service (in memory), the standalone service's **REST client** (over HTTP, as a service account), and this app's **Frappe client** (in process, as the signed-in person). The same 44 checks, written once in `ai_munimji_engine.testkit` and run against the same data, are held against all three.

Run on 6 November 2026, on the development site: Frappe 16.55.2, ERPNext 16.54.0, the contract world loaded by `dev/scripts/load_contract_world.py` (company "Munimji Demo Co"). Nothing here is a claim about any other version.

## The three clients, on the same data

The Frappe client is run as Administrator here, which has every right, so that the table compares what the three clients *do* with the same data and not who may see it.

| Check | Kind | Demo ERP | REST client | Frappe client |
|---|---|---|---|---|
| healthcheck_is_true | reads | pass | pass | pass |
| list_items_lists_stock_items_and_leaves_out_disabled_and_services | reads | pass | pass | pass |
| list_items_carries_name_unit_and_lead_time | reads | pass | pass | pass |
| list_items_begins_an_items_history_at_its_first_stock_movement | reads | pass | pass | pass |
| list_warehouses_leaves_out_groups_and_disabled_ones | reads | pass | pass | pass |
| get_stock_sums_the_shelves_of_an_item | reads | pass | pass | pass |
| get_stock_says_what_is_on_each_shelf | reads | pass | pass | pass |
| get_stock_can_be_limited_to_some_warehouses | reads | pass | pass | pass |
| get_stock_gives_zero_for_an_item_with_no_stock_or_no_record | reads | pass | pass | pass |
| get_stock_reserves_what_an_open_sales_order_holds | reads | pass | pass | pass |
| get_stock_counts_an_order_on_its_way_and_says_when_it_is_due | reads | pass | pass | pass |
| get_stock_reports_stock_in_transit_apart | reads | pass | pass | pass |
| get_consumption_gives_the_days_something_was_used | reads | pass | pass | pass |
| get_consumption_keeps_to_the_window | reads | pass | pass | pass |
| get_consumption_keeps_to_the_warehouses_asked_for | reads | pass | pass | pass |
| get_consumption_is_empty_for_an_item_nothing_was_sold | reads | pass | pass | pass |
| get_open_sales_orders_says_what_is_still_to_deliver | reads | pass | pass | pass |
| get_vendor_offers_counts_orders_and_prices | reads | pass | pass | pass |
| get_vendor_offers_works_out_delivery_time_and_punctuality | reads | pass | pass | pass |
| get_vendor_offers_reads_payment_terms_and_the_item_supplier_list | reads | pass | pass | pass |
| get_vendor_offers_includes_a_listed_supplier_that_was_never_ordered_from | reads | pass | pass | pass |
| get_vendor_offers_leaves_out_a_disabled_supplier | reads | pass | pass | pass |
| get_vendor_offers_looks_only_as_far_back_as_asked | reads | pass | pass | pass |
| get_vendor_offers_adds_a_valid_quotation_when_asked | reads | pass | pass | pass |
| get_vendor_offers_says_nothing_of_quotations_unless_asked | reads | pass | pass | pass |
| item_min_order_qty_is_the_items_own | reads | pass | pass | pass |
| get_purchase_taxes_follows_the_tax_rule | reads | pass | pass | pass |
| get_purchase_taxes_does_not_invent_a_template | reads | pass | pass | pass |
| find_by_reference_finds_the_order_made_for_a_request | reads | pass | pass | pass |
| get_documents_by_name_reads_one_order | reads | pass | pass | pass |
| get_documents_by_item_finds_every_order_of_it_and_since_cuts_old_ones | reads | pass | pass | pass |
| get_documents_open_only_leaves_out_finished_orders | reads | pass | pass | pass |
| get_documents_limit_is_honoured | reads | pass | pass | pass |
| create_purchase_order_makes_a_draft_with_the_reference_and_the_approver | writes | pass | pass | pass |
| pressing_create_twice_gives_one_order | writes | pass | pass | pass |
| a_cancelled_order_and_its_replacement_share_a_reference_and_the_replacement_is_accepted | writes | pass | pass | pass |
| an_order_made_by_hand_is_left_alone | writes | pass | pass | pass |
| create_material_request_makes_a_draft_and_is_safe_to_repeat | writes | pass | pass | pass |
| create_stock_transfer_makes_a_draft_and_refuses_the_same_warehouse | writes | pass | pass | pass |
| update_purchase_order_qty_changes_a_draft | writes | pass | pass | pass |
| update_purchase_order_qty_changes_a_submitted_order_and_keeps_it_submitted | writes | pass | pass | pass |
| cancel_purchase_order_deletes_a_draft_and_a_second_try_finds_it_gone | writes | pass | pass | pass |
| cancel_purchase_order_cancels_a_submitted_one | writes | pass | pass | pass |
| cancel_purchase_order_refuses_an_order_with_another_reference | writes | pass | pass | pass |
| **Total** | | 44 pass | 44 pass | 44 pass |

**All 44 checks give the same result in all three columns.** The REST client was run over HTTP against this very site (about 8 minutes: one request per page of rows), the demo ERP in memory, the Frappe client in process (4 seconds).

## The Frappe client, by person

The point of the Frappe client is that it is the person who is signed in. Here are the same 44 checks, run as the three kinds of person that `docs/INSTALL.md` speaks of. A check does not pass when the ERP refuses that person something the check needs; every difference below is a permission, never a different answer to the same question.

| Check | Kind | Demo ERP | REST client | Frappe client | Frappe, Purchase User + Stock User | Frappe, Stock User | Frappe, Munimji role only |
|---|---|---|---|---|---|---|---|
| healthcheck_is_true | reads | pass | pass | pass | pass | pass | pass |
| list_items_lists_stock_items_and_leaves_out_disabled_and_services | reads | pass | pass | pass | pass | pass | ERROR |
| list_items_carries_name_unit_and_lead_time | reads | pass | pass | pass | pass | pass | ERROR |
| list_items_begins_an_items_history_at_its_first_stock_movement | reads | pass | pass | pass | pass | pass | ERROR |
| list_warehouses_leaves_out_groups_and_disabled_ones | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_sums_the_shelves_of_an_item | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_says_what_is_on_each_shelf | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_can_be_limited_to_some_warehouses | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_gives_zero_for_an_item_with_no_stock_or_no_record | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_reserves_what_an_open_sales_order_holds | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_counts_an_order_on_its_way_and_says_when_it_is_due | reads | pass | pass | pass | pass | pass | ERROR |
| get_stock_reports_stock_in_transit_apart | reads | pass | pass | pass | pass | pass | ERROR |
| get_consumption_gives_the_days_something_was_used | reads | pass | pass | pass | pass | pass | ERROR |
| get_consumption_keeps_to_the_window | reads | pass | pass | pass | pass | pass | ERROR |
| get_consumption_keeps_to_the_warehouses_asked_for | reads | pass | pass | pass | pass | pass | ERROR |
| get_consumption_is_empty_for_an_item_nothing_was_sold | reads | pass | pass | pass | pass | pass | ERROR |
| get_open_sales_orders_says_what_is_still_to_deliver | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_counts_orders_and_prices | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_works_out_delivery_time_and_punctuality | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_reads_payment_terms_and_the_item_supplier_list | reads | pass | pass | pass | pass | FAIL | ERROR |
| get_vendor_offers_includes_a_listed_supplier_that_was_never_ordered_from | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_leaves_out_a_disabled_supplier | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_looks_only_as_far_back_as_asked | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_adds_a_valid_quotation_when_asked | reads | pass | pass | pass | pass | pass | ERROR |
| get_vendor_offers_says_nothing_of_quotations_unless_asked | reads | pass | pass | pass | pass | pass | ERROR |
| item_min_order_qty_is_the_items_own | reads | pass | pass | pass | pass | pass | ERROR |
| get_purchase_taxes_follows_the_tax_rule | reads | pass | pass | pass | ERROR | ERROR | ERROR |
| get_purchase_taxes_does_not_invent_a_template | reads | pass | pass | pass | ERROR | ERROR | ERROR |
| find_by_reference_finds_the_order_made_for_a_request | reads | pass | pass | pass | pass | pass | ERROR |
| get_documents_by_name_reads_one_order | reads | pass | pass | pass | pass | pass | ERROR |
| get_documents_by_item_finds_every_order_of_it_and_since_cuts_old_ones | reads | pass | pass | pass | pass | pass | ERROR |
| get_documents_open_only_leaves_out_finished_orders | reads | pass | pass | pass | pass | pass | ERROR |
| get_documents_limit_is_honoured | reads | pass | pass | pass | pass | pass | ERROR |
| create_purchase_order_makes_a_draft_with_the_reference_and_the_approver | writes | pass | pass | pass | pass | FAIL | FAIL |
| pressing_create_twice_gives_one_order | writes | pass | pass | pass | pass | FAIL | FAIL |
| a_cancelled_order_and_its_replacement_share_a_reference_and_the_replacement_is_accepted | writes | pass | pass | pass | pass | FAIL | FAIL |
| an_order_made_by_hand_is_left_alone | writes | pass | pass | pass | pass | FAIL | ERROR |
| create_material_request_makes_a_draft_and_is_safe_to_repeat | writes | pass | pass | pass | pass | pass | FAIL |
| create_stock_transfer_makes_a_draft_and_refuses_the_same_warehouse | writes | pass | pass | pass | pass | pass | FAIL |
| update_purchase_order_qty_changes_a_draft | writes | pass | pass | pass | pass | FAIL | FAIL |
| update_purchase_order_qty_changes_a_submitted_order_and_keeps_it_submitted | writes | pass | pass | pass | pass | FAIL | FAIL |
| cancel_purchase_order_deletes_a_draft_and_a_second_try_finds_it_gone | writes | pass | pass | pass | pass | FAIL | FAIL |
| cancel_purchase_order_cancels_a_submitted_one | writes | pass | pass | pass | pass | FAIL | FAIL |
| cancel_purchase_order_refuses_an_order_with_another_reference | writes | pass | pass | pass | pass | pass | ERROR |
| **Total** | | 44 pass | 44 pass | 44 pass | 42 pass, 2 error | 33 pass, 9 fail, 2 error | 1 pass, 9 fail, 34 error |

Why each column differs from Administrator:

* **Purchase User + Stock User** (the approver): 42 of 44. The 2 errors are the two checks that read the **Tax Rule**, which needs the Accounts Manager role. This is the case the tax figures kept with a request are for (INSTALL.md, "Taxes in a request").
* **Stock User** (a viewer): 33 pass, 9 fail, 2 error.
  * 2 errors: the same Tax Rule reads.
  * 1 fail, `get_vendor_offers_reads_payment_terms_and_the_item_supplier_list`: the vendor's credit days are on the Payment Terms Template, which a Stock User may not read, so they come back unknown (`None`), not guessed. Everything else that check looks at is right.
  * 8 fails: the checks that **make a Purchase Order** first (create, press twice, replace a cancelled order, the order made by hand, change a draft, change a submitted order, delete a draft, cancel a submitted order). A Stock User may not create a Purchase Order ("may not create a purchase order: insufficient permission"). The Material Request and Stock Entry checks, which a Stock User may make, pass.
* **Only a Munimji role** (no ERPNext right): 1 pass (the health check, which reads no business data); everything else is refused with a `PermissionError` that names the person and the DocType. No read returns an empty list in place of a refusal.

These columns are pinned by `ai_munimji/tests/world/test_permissions.py` (13 reads and 5 writes, each checked against `frappe.has_permission`), so a change in who gets what fails a test.

## How to repeat it

```
python tools/contract_report.py demo --out demo.json                  # in the standalone repository
.\dev\contract-rest.ps1                                               # the REST client over HTTP against this bench: writes dev\contract-rest.json
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/contract_report.py /workspace/ai_munimji/dev/contract-frappe-Administrator.json Administrator
                                                                       # also approver, viewer, neither (the script makes and removes those users)
python tools/contract_table.py "Demo ERP=demo.json" "REST client=dev/contract-rest.json" "Frappe client=dev/contract-frappe-Administrator.json"
```
