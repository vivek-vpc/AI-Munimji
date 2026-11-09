# Development environment

A Frappe v16 + ERPNext v16 bench in Docker, for building and testing the `ai_munimji` app. It is Frappe's official dev-container example
(`frappe_docker`, `devcontainer-example`), run from the command line with two changes for Windows (see the comments in `compose.yml`).
It is its own compose project, `munimji-dev`; it does not touch other Docker projects.

You need Docker Desktop (about 6 GB for its virtual machine; 8 recommended) and about 10 GB of free disk. Nothing else is installed on Windows.
The rules package `ai-munimji-engine` is not on PyPI: the wheel comes from the `erpnext-ai-agents` repository (next to this one) and is built by `.\dev\build-engine-wheel.ps1`.

## The commands you run

From `C:\ERP\AI-Munimji` in PowerShell:

```
.\dev\build-engine-wheel.ps1   # the engine wheel, from ..\erpnext-ai-agents\engine, into dev\wheels\ (not in git)
.\dev\up.ps1                   # pull the images (about 0.9 GB the first time) and start 4 containers, 2 volumes, 1 network
```

Then, once (about 45 to 70 minutes the first time, mostly downloads and the asset build; it installs the engine wheel before the app):

```
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/bootstrap.sh
```

Every step's duration is appended to `dev/timings.log`.

Day to day:

```
.\dev\shell.ps1                       # a shell in the bench directory inside the container
.\dev\exec.ps1 bench start            # web on http://development.localhost:8000 (Administrator / admin), realtime on 9000
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/gate.sh      # the app's tests, bandit, pip-audit (the checks before a commit)
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/check-uninstall.sh      # install, migrate twice, uninstall, install again, on a new site (about 5 minutes)
.\dev\verify-all.ps1 -Fresh           # everything from nothing, with a timing table (about 25 minutes)
.\dev\down.ps1                        # stop the containers, keep the data
.\dev\precommit.ps1                    # the repository's formatters and linters (ruff, prettier, eslint) on the files git shows as changed
python dev/scripts/make_doctypes.py     # write the DocType files and the table of docs/STORES.md from ai_munimji/stores/specs.py (--check changes nothing)
.\dev\permissions-http.ps1             # who sees and answers what, asked over HTTP as five real people (starts the bench if it is not running)
.\dev\world-tests.ps1                   # the Frappe client and the stores on real data (the contract world must be loaded: -Load)
.\dev\scripts\bench_tests.ps1 <module>   # one module of the app's tests on the test site, with a short verdict
.\dev\destroy.ps1                     # remove containers, network and the two volumes of this project (asks first)
```

`development.localhost` resolves to your own machine in current browsers; no hosts-file change is needed. The ports are published on 127.0.0.1 only.

After you change a DocType file, bring the sites up to date with `bench --site <site> migrate` (the test site is `test.localhost`).

## What is in it

| | |
|---|---|
| `compose.yml` | MariaDB 11.8, two Redis, and the `frappe/bench` image (Python 3.14, Node 24, bench 5.x), pinned by digest |
| `up.ps1`, `down.ps1`, `destroy.ps1`, `shell.ps1`, `exec.ps1` | the commands above |
| `lib.sh`, `bootstrap.sh` | run inside the container; `bootstrap.sh` builds the bench, installs the engine, ERPNext and the app |
| `build-engine-wheel.ps1`, `install-engine.sh` | get the engine into the bench: the one place that knows how (README, "The engine") |
| `gate.sh`, `run-tests.sh`, `semgrep.ps1` | the checks; `gate.sh` audits the engine's dependencies as installed |
| `check-uninstall.sh`, `scripts/snapshot.py`, `scripts/diff_snapshots.py`, `scripts/check_coexistence.py`, `scripts/standalone_fields.py` | the uninstall check, with a site that already has the standalone service's fields |
| `verify-all.ps1` | all of it from nothing |
| `roundtrip.ps1`, `browser/round-trip.cjs`, `scripts/seed.py`, `scripts/reset_demo.py` | the end-to-end trial of the placeholder below |
| `images.lock` | the image digests that were really used (written by `up.ps1`) |
| `timings.log` | how long each step took (not in git) |

## Placeholders: replaced in Phase 5

These are the first experiment's, kept so that the app can be tried end to end. They are marked in the code with the words "replaced in Phase 5".

* `ai_munimji/jobs.py` (`check_stock`): the scheduled entry. It runs the engine's stock check (`run_stock_check`) every 5 minutes at the soonest, and only while Watch stock is ticked. Phase 5 gives it
  the schedule the settings page names.
* The list **Munimji Approval Request**: its form has one button, "Create Purchase Order", which calls `ai_munimji.api.answer`. Phase 5 builds the approval form with the reasoning, the inbox and
  the notifications.
* `scripts/seed.py`, `scripts/reset_demo.py`, `roundtrip.ps1` and `browser/round-trip.cjs`, which exist for the two above (the demo's requests are made by `reset_demo.py`, which does what the job and
  a person's approval would, so that the round trips do not depend on when the scheduler ticks).

Everything else (settings, roles, fields, uninstall, the engine dependency, the tests that read the code) is the app proper.
