# Names

The names of the app and of what it adds to a site, written down once. A name that changes is a decision for the project owner.

| What | Name |
|---|---|
| Frappe app (the Python package and `app_name`) | `ai_munimji` |
| Title | AI Munimji |
| Module | AI Munimji |
| Settings page (Single DocType) | AI Munimji Settings |
| Other DocTypes | Munimji Approval Request, Munimji Calendar Event (a table inside the settings) |
| Roles | Munimji Viewer, Munimji Approver, Munimji Manager |
| Permission Type | `approve` on Munimji Approval Request |
| The rules package | `ai-munimji-engine` (import name `ai_munimji_engine`) |
| The standalone service it shares rules with | `erpnext-ai-agents` (command `erp-agents`, package `erp_agents`) |

## The fields added to ERPNext's documents

| DocType | Field | Type | Holds |
|---|---|---|---|
| Purchase Order | `custom_agent_ref` | Data, indexed, not unique | the request the order was made from |
| Purchase Order | `custom_agent_approved_by` | Data | who approved it and from where, for example `priya@example.com via desk` |
| Material Request | `custom_agent_ref`, `custom_agent_approved_by` | Data | the same two |
| Material Request | `custom_agent_note` | Small Text | the recommendation for the buyer |
| Stock Entry | `custom_agent_ref`, `custom_agent_approved_by` | Data | the same two |

All seven are read-only, are not copied when a document is copied, and are hidden in print. They are the **same names, types, positions and settings as the ones `erp-agents erp-setup` makes** for the standalone service (`erpnext-ai-agents`, `src/erp_agents/core/erp/erpnext.py`, `ERPNextClient.CUSTOM_FIELDS`, commit 7f9bb9d). Only the labels ("Munimji request", "Approved by (Munimji)", "Munimji note") and the descriptions are this app's own words.

### Why not `custom_munimji_approver` and `custom_munimji_note`

The first plan named the fields `custom_munimji_approver` and `custom_munimji_note`. They were changed to the standalone's names, on purpose, for three reasons:

1. **Each product recognises the other's orders by the reference field.** Before creating an order the service looks for one that already carries the request's reference; it refuses to change or cancel an order that does not. A site that has used the service already has `custom_agent_ref` on its Purchase Orders. With a second name the app would not see those orders, and the service would not see the app's, so a request could be ordered twice.
2. **The approver is text, not a link.** The service writes who approved and where from (`priya@example.com via app`, `owner via whatsapp`). A link to a User cannot hold that; the spike's `custom_agent_approver` (a link) is gone for the same reason. The app writes the same form of words: `user via desk`.
3. **The reference is not unique.** The service finds an order by its reference among the documents that are not cancelled (docstatus below 2), so a cancelled order and the order that replaces it carry the same reference. A unique field would make the database refuse the replacement (the spike's did; `test_a_cancelled_order_and_its_replacement_may_carry_the_same_reference` shows it does not now). One request becomes one order by other means: the row is locked while the order is made, and a request that already has a live order is refused.

`ai_munimji/tests/test_custom_fields.py` keeps a copy of the service's table and fails if the app's fields drift from it. If the service changes its fields, change both together.
