# AI Munimji

A Frappe app for ERPNext v16 that watches stock and prepares draft purchase orders for a person to approve. This is version 0.1.0, the first version: it covers stock monitoring, supplier comparison and approval, and [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) lists what it does not do yet. It has been run only on Frappe 16.55.2 and ERPNext 16.54.0 (earlier checks were on 16.53.0), in a development container and in CI.

The rules the app is built to:

* The rules decide; a language model, if one is ever used, only explains. Version 0.1 calls no model and sends nothing out of the site.
* Nothing is approved by the app itself. A person answers every request.
* ERPNext receives **draft** documents, with the approver recorded and the request's reference in a field. The app never submits one. An approver can later change the quantity of, or cancel, an order made from a request.
* Every method a browser can call checks the caller's permission first, and only the scheduled job reads with `frappe.get_all`. A test enforces both (`ai_munimji/tests/test_rules.py`).

## What is in version 0.1.0

| | |
|---|---|
| The settings page, **AI Munimji Settings** | the values of the stock rules, the check schedule, the demand calendar, how long a request waits, stock alerts and a fallback supplier; checked by the same rules as the standalone service's `settings.yaml` |
| Three roles | Munimji Viewer, Munimji Approver, Munimji Manager; every right of each is pinned by a test |
| Seven read-only fields on Purchase Order, Material Request and Stock Entry | the same fields the standalone service writes, so either product recognises the other's orders ([docs/NAMES.md](docs/NAMES.md)) |
| An uninstall that is tested | [docs/UNINSTALL.md](docs/UNINSTALL.md) |
| The engine's records as DocTypes | 25 of them: requests, purchase proposals, alerts, work orders, the audit seal and the rest; who may do what to each, how a value is kept, the locks and the clean-up are in [docs/STORES.md](docs/STORES.md) |
| The stock check on a schedule | a job that the Settings page switches on and off and sets the time of; off until a person ticks Watch stock |
| The approval form | the request in words, drawn from what the engine stored (the stock, why this vendor, why the others were not chosen, cost, delivery, taxes, the order that approving makes), with the buttons Approve, Change quantity, Change vendor and Dismiss; the first answer wins and the second is told who answered first |
| A notification | one in the Desk bell of each Approver when a request is made, once per request; no e-mail |
| **Not built yet** | a dry run, a stock monitor view, an inbox beyond the standard list view, reminders and expiry, e-mail notifications; the list is in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) |

To install it on a bench you run yourself, see [docs/INSTALL.md](docs/INSTALL.md), which also says which ERPNext roles a person needs to see stock and make orders.

## The engine (for developers)

The rules (stock analysis, vendor scoring, the settings models) live in a separate package, `ai-munimji-engine`, built from the `erpnext-ai-agents` repository and published on PyPI. The app pins it exactly in one line of `pyproject.toml` (`dependencies`), so installing the app installs that version, and CI installs the same version from PyPI. When you work on the app, a local wheel of the engine can be put into the bench's environment first, so that an engine that is not published yet can be tried:

```
.\dev\build-engine-wheel.ps1       # builds dev\wheels\ai_munimji_engine-<version>-py3-none-any.whl from ..\erpnext-ai-agents\engine
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh      # installs the newest wheel in dev/wheels into the bench (bootstrap.sh and verify-all.ps1 do both for you)
```

`dev/install-engine.sh` is the only place that knows how the development engine arrives. `ai_munimji/tests/test_engine_wheel.py` checks, inside the bench, that the installed engine is the wheel, satisfies the declared line, brings nothing but pydantic and PyYAML, imports in full and runs.

## Development

[dev/README.md](dev/README.md) describes the development environment (a Frappe v16 and ERPNext v16 bench in Docker) and the checks: `.\dev\verify-all.ps1 -Fresh` rebuilds everything from nothing and runs them all.

Words a person reads go through `_()` in Python and `__()` in JavaScript; `ai_munimji/locale/main.pot` is the template of the translations, made by `bench --site <site> generate-pot-file --app ai_munimji`, and a test fails on any word that is not wrapped.

Licence: GPL-3.0-or-later.
