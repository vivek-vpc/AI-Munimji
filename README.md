# AI Munimji

A Frappe app for ERPNext v16 that watches stock and prepares purchase requests for a person to approve. **It is at an early stage of development.** It is not released, not listed on the Frappe Marketplace, and not installable from it. It has been run only on Frappe 16.55.2 and ERPNext 16.54.0 (earlier checks were on 16.53.0), in a development container.

The rules the app is built to:

* The rules decide; a language model, if one is ever used, only explains. Version 0.1 calls no model and sends nothing out of the site.
* Nothing is approved by the app itself. A person answers every request.
* ERPNext receives **draft** documents only, with the approver recorded and the request's reference in a field.
* Every method a browser can call checks the caller's permission first, and only the scheduled job reads with `frappe.get_all`. A test enforces both (`ai_munimji/tests/test_rules.py`).

## What is in this branch

| | |
|---|---|
| The settings page, **AI Munimji Settings** | the values of the stock rules, the check schedule, the demand calendar, how long a request waits, stock alerts and a fallback supplier; checked by the same rules as the standalone service's `settings.yaml` |
| Three roles | Munimji Viewer, Munimji Approver, Munimji Manager; every right of each is pinned by a test |
| Seven read-only fields on Purchase Order, Material Request and Stock Entry | the same fields the standalone service writes, so either product recognises the other's orders ([docs/NAMES.md](docs/NAMES.md)) |
| An uninstall that is tested | [docs/UNINSTALL.md](docs/UNINSTALL.md) |
| **Placeholders, replaced in Phase 5** | the list Munimji Approval Request with its "Create Purchase Order" button, and a scheduled job that asks for a purchase wherever a warehouse holds no more than a quantity. They are the first experiment's, kept so that the app can be tried end to end |

To install it on a bench you run yourself, see [docs/INSTALL.md](docs/INSTALL.md), which also says which ERPNext roles a person needs to see stock and make orders.

## The engine (for developers)

The rules (stock analysis, vendor scoring, the settings models) live in a separate package, `ai-munimji-engine`, built from the `erpnext-ai-agents` repository. It is **not on PyPI**, and nothing is published. The app lists it as one line in `pyproject.toml` (`dependencies`). Until it is published, a local wheel is put into the bench's environment before the app is installed or updated, because the installer would otherwise look for it on PyPI and stop:

```
.\dev\build-engine-wheel.ps1       # builds dev\wheels\ai_munimji_engine-<version>-py3-none-any.whl from ..\erpnext-ai-agents\engine
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh      # installs the newest wheel in dev/wheels into the bench (bootstrap.sh and verify-all.ps1 do both for you)
```

`dev/install-engine.sh` is the only place that knows how the engine arrives. The day it is published, nothing in the code changes: the dependency line already names it, and the script is dropped. `ai_munimji/tests/test_engine_wheel.py` checks, inside the bench, that the installed engine is the wheel, satisfies the declared line, brings nothing but pydantic and PyYAML, imports in full and runs.

## Development

[dev/README.md](dev/README.md) describes the development environment (a Frappe v16 and ERPNext v16 bench in Docker) and the checks: `.\dev\verify-all.ps1 -Fresh` rebuilds everything from nothing and runs them all.

Words a person reads go through `_()` in Python and `__()` in JavaScript; `ai_munimji/locale/main.pot` is the template of the translations, made by `bench --site <site> generate-pot-file --app ai_munimji`, and a test fails on any word that is not wrapped.

Licence: GPL-3.0-or-later.
