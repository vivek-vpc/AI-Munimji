# Installing AI Munimji, and who needs which role

AI Munimji is **not released**. It is not on the Frappe Marketplace and you cannot install it from there. These notes are for people who run the source on their own bench. It has been run only on **Frappe 16.55.2 and ERPNext 16.53.0** (version 16 of both; nothing older or newer has been tried).

## What you need first

* A bench with Frappe 16 and ERPNext 16 and a site with ERPNext installed (`required_apps` in `hooks.py` says ERPNext is a must).
* The rules package, `ai-munimji-engine`. It is not on PyPI, so before the app is installed or updated it has to be put into the bench's Python environment from a local wheel: see the README, "The engine". If you skip that, installing the app stops with `ai-munimji-engine was not found in the package registry`.

```
bench get-app <the folder of this repository>          # after the engine is in the environment
bench --site <your site> install-app ai_munimji
```

## What installing adds to your site

| What | Where |
|---|---|
| Three roles: Munimji Viewer, Munimji Approver, Munimji Manager | Role |
| The page AI Munimji Settings (Search "AI Munimji Settings"), with a calendar table | Single DocType |
| The list Munimji Approval Request | DocType |
| An "approve" permission for that list | Permission Type |
| Seven read-only fields that carry the request's reference and who approved: `custom_agent_ref` and `custom_agent_approved_by` on Purchase Order, Material Request and Stock Entry, and `custom_agent_note` on Material Request | Custom Field |
| A scheduled job, every 5 minutes at the soonest (ERPNext's scheduler runs a job every 4 minutes at the soonest) | Scheduled Job Type |

The app adds **no permission rows to any ERPNext DocType**. What a person may see or do in ERPNext is decided by ERPNext's own roles, and the Munimji roles decide only what they may do with the app's own pages.

## Who needs which role

| A person who... | Munimji role | ERPNext roles they also need |
|---|---|---|
| looks at the requests | Munimji Viewer | **Stock User**, to see the stock the requests are about (Item, Bin, Stock Ledger Entry, Warehouse) |
| answers a request, which makes a **draft** Purchase Order under their own login | Munimji Approver | **Stock User**, and **Purchase User** to create the draft. The service's README also names Purchase Manager; on ERPNext 16.53.0 Purchase User alone is enough to create a Purchase Order (tested), so Purchase Manager is needed only if your own setup asks for it |
| changes the settings, and may delete requests | Munimji Manager | the same as an approver if they also answer requests |
| everything | System Manager | none |

A person with only a Munimji role reads nothing of ERPNext's (no Item, Bin, Stock Ledger Entry or Purchase Order). That is intended.

Approving needs two things at once: the Munimji "approve" right, and the right to create a Purchase Order in ERPNext. Someone who has one without the other is refused, and nothing is created.

## Settings

Open AI Munimji Settings as a Munimji Manager or System Manager. The values are checked by the same rules as the standalone service uses for its `settings.yaml`, so a value is accepted here exactly when the service accepts it there. The time zone is the one in System Settings. There are no secrets in version 0.1.

## Taking it out

See [UNINSTALL.md](UNINSTALL.md).
