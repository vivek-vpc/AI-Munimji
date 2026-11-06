# AI Munimji

A Frappe app for ERPNext v16, planned to help with stock monitoring and purchase requests. **This repository is at its very beginning.** It is not released, not listed on the Frappe Marketplace, and not installable from it.

What is here, branch by branch:

- `main`: this file and nothing else.
- `frappe/1-spike`: a throw-away spike that checks, on a real bench, how the pieces fit (one DocType, one scheduled job, one approval that creates a draft Purchase Order, and an uninstall). It is a measurement, not a feature, and it has been run only on Frappe v16 and ERPNext v16 in a development container.

The rules the app is being built to: rules decide and a language model, if one is ever used, only explains; nothing is approved by the app itself; ERPNext receives draft documents only, with the approver recorded; version 0.1 sends nothing out of the site and calls no model.

## The engine (for developers)

The rules (stock analysis, vendor scoring, the settings models) live in a separate package, `ai-munimji-engine`, built from the `erpnext-ai-agents` repository. It is **not on PyPI**, and nothing is published. The app lists it as one line in `pyproject.toml` (`dependencies`). Until it is published, a local wheel is put into the bench's environment before the app is installed or updated, because the installer would otherwise look for it on PyPI and stop:

```
.\dev\build-engine-wheel.ps1       # builds dev\wheels\ai_munimji_engine-<version>-py3-none-any.whl from ..\erpnext-ai-agents\engine
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/install-engine.sh      # installs the newest wheel in dev/wheels into the bench (bootstrap.sh and verify-all.ps1 do both for you)
```

`dev/install-engine.sh` is the only place that knows how the engine arrives. The day it is published, nothing in the code changes: the dependency line already names it, and the script is dropped. `ai_munimji/tests/test_engine_wheel.py` checks, inside the bench, that the installed engine is the wheel, satisfies the declared line, brings nothing but pydantic and PyYAML, imports in full and runs.

Licence: GPL-3.0-or-later.
