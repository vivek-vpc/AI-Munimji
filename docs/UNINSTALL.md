# Taking AI Munimji out

```
bench --site <your site> uninstall-app ai_munimji
```

`bench uninstall-app` takes a backup of the site first, unless you pass `--no-backup`; keep it if the requests or the settings matter, because they are deleted with the app. `--dry-run` lists the DocTypes that would be deleted. To remove the app from the bench as well: `bench remove-app ai_munimji`.

## What goes

* **With the app itself** (Frappe removes these): the DocTypes AI Munimji Settings, Munimji Approval Request and Munimji Calendar Event, **with every record in them** (so the settings and all requests are deleted), the module, and the app's entry.
* **Removed by the app's own uninstall step** (`before_uninstall`): the three roles Munimji Viewer, Munimji Approver and Munimji Manager, and their assignment to users; the seven Custom Fields `custom_agent_ref` and `custom_agent_approved_by` (on Purchase Order, Material Request and Stock Entry) and `custom_agent_note` (on Material Request); the "approve" permission type; and the scheduled job.

## What stays

The uninstall prints this, and it is the same text here (a test compares them).

- The database columns custom_agent_ref, custom_agent_approved_by and custom_agent_note on Purchase Order, Material Request and Stock Entry stay, with their values and the index on custom_agent_ref. Frappe never drops a column when a field is deleted, so that no data is lost.
- Every Purchase Order, Material Request and Stock Entry that was already made, drafts included, stays as it is. None is changed or deleted.
- The empty column approve stays in the tables DocPerm, Custom DocPerm and DocShare, where the permission type approve put it. Frappe does not drop it when the permission type is deleted, and it is shared by name with any other permission type called approve, so it is left alone. Installing again reuses it.
- The package ai-munimji-engine stays in the bench's Python environment. Remove it with: pip uninstall ai-munimji-engine
- If the standalone service (erp-agents) also works on this site, it needs the seven fields that were just removed. Run erp-agents erp-setup again; it makes them again and finds the columns in place.

## Installing it again

A second install on the same site works and gives what the first one gave: the roles, the fields (they reuse the columns that stayed, and so the references on old orders are visible again), the settings page with its default values, and no requests. The settings you had are not kept.

## What is checked

`dev/check-uninstall.sh` builds a fresh site with ERPNext only and compares what it holds at five moments: before the app (A), with it installed (B), after two `bench migrate` runs (B2, B3), after the uninstall (C) and after installing it again (D). It requires that A and C differ only by the columns that stay, and that B, B2, B3 and D are the same. It then repeats the uninstall on a site that already had the standalone service's fields (E). The result of the last run is in the Phase 3 report.
