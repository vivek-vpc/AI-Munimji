# Development environment

A Frappe v16 + ERPNext v16 bench in Docker, for building and testing the `ai_munimji` app. It is Frappe's official dev-container example
(`frappe_docker`, `devcontainer-example`), run from the command line with two changes for Windows (see the comments in `compose.yml`).
It is its own compose project, `munimji-dev`; it does not touch other Docker projects.

You need Docker Desktop (about 6 GB for its virtual machine; 8 recommended) and about 10 GB of free disk. Nothing else is installed on Windows.
The rules package `ai-munimji-engine` is on PyPI and the app pins it exactly. This environment installs a wheel of it built from the `erpnext-ai-agents` repository (next to this one) by `.\dev\build-engine-wheel.ps1` instead, so that an engine that is not published yet can be tried.

## The commands you run

From the folder of this repository, in PowerShell:

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
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/check-upgrade.sh        # the code of an earlier tag (v0.1.1 unless you name another) on a new site, then the working tree and `bench migrate` twice: what a person had is kept (about 5 minutes)
.\dev\verify-all.ps1 -Fresh           # everything from nothing, with a timing table (about 25 minutes)
.\dev\down.ps1                        # stop the containers, keep the data
.\dev\precommit.ps1                    # the repository's formatters and linters (ruff, prettier, eslint) on the files git shows as changed
python dev/scripts/make_doctypes.py     # write the DocType files and the table of docs/STORES.md from ai_munimji/stores/specs.py (--check changes nothing)
.\dev\permissions-http.ps1             # who sees and answers what, asked over HTTP as five real people (starts the bench if it is not running)
.\dev\world-tests.ps1                   # the Frappe client and the stores on real data (the contract world must be loaded: -Load)
.\dev\telegram-e2e.ps1                 # a request from the stock check to a Draft Purchase Order through Telegram, over HTTP, against a pretend Telegram (-Browser also drives the Settings page and the Connect dialog)
.\dev\scripts\bench_tests.ps1 <module>   # one module of the app's tests on the test site, with a short verdict
.\dev\destroy.ps1                     # remove containers, network and the two volumes of this project (asks first)
```

`development.localhost` resolves to your own machine in current browsers; no hosts-file change is needed. The ports are published on 127.0.0.1 only.

* **`bench start` says "address already in use :::9000" and stops:** a `bench start` from earlier is still running in the container and is serving the site already. Stop it with `docker exec munimji-dev-frappe-1 pkill -f honcho` if you want a fresh one.
* **The app's place on the Desk** (the tile, the sidebar, the home page) is three exported files: `ai_munimji/dock/`, `ai_munimji/ai_munimji/sidebar/` and `ai_munimji/ai_munimji/workspace/`. On the development site (developer mode) they are written by Frappe when the record is saved on the Desk, so edit them there and look at the diff. `tests/test_desk.py` checks that they agree with `hooks.py` and with the DocTypes.
* **Do not run `bench uninstall-app ai_munimji` on the development site:** in developer mode Frappe deletes the exported Workspace and Sidebar files from the app's folder (`git checkout -- ai_munimji` brings them back). Use `check-uninstall.sh`, which works on a separate site.

After you change a DocType file, bring the sites up to date with `bench --site <site> migrate` (the test site is `test.localhost`).

## Measuring at scale

`docs/SCALE_MEASUREMENTS.md` has the numbers; these are the tools. They write millions of rows, so they run on a **separate site** that no person opens, never on `development.localhost` (each script
stops if the site's name does not start with `scale`):

```
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/make-site.sh scale.localhost app          # a site with ERPNext and the app (about 5 minutes)
# the company, a supplier and the demo users, then the stock: 30,000 items, 5 million ledger rows (about 8 minutes)
.\dev\exec.ps1 bash -c "cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed.py"
.\dev\exec.ps1 bash -c "cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_scale.py 30000 167"
.\dev\exec.ps1 bash -c "cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_hot.py 3 100000"
.\dev\exec.ps1 bench --site scale.localhost scheduler disable        # ERPNext's job that renames ledger entries would otherwise rewrite the seeded rows while you measure
```

* `scripts/measure_stock_check.py <items> [dismiss|approve|none]`: one stock check, its time, peak memory, the longest time it held row locks (the database's transaction list, read as its root user), and what
  20 people who answer the requests it is replacing, as soon as it has begun to, are made to wait.
* `scripts/measure_ledger_reads.py items|consumption <n>|hot|one`: what the ERP client reads from the stock ledger (time, peak memory, rows fetched into Python).
* `scripts/seed_audit.py <n>`, `scripts/measure_audit_sweep.py`: the audit sweep over a sealed history of n requests, with nothing new to seal. `scripts/measure_retention.py <n> [runs]`: the daily clean-up over a backlog.
* `scripts/seed_load.py` and `loadtest.py` (run in the container): 100 approvers with API keys and 100 requests waiting, then three crowds over HTTP: 100 different approvals at once, 20 presses on one request, and
  100 people opening the list and a form while a stock check runs. It needs the app served by a real web server, not the development server: `bench` on the site's folder,
  `env/bin/gunicorn -b 127.0.0.1:8001 -w 4 -t 300 frappe.app:application --preload`, from `sites/`.
* To measure the code as it was committed against the code in the working tree, put the committed `ai_munimji` folder somewhere (`git archive HEAD ai_munimji`) and run a script with `PYTHONPATH=<that folder>`.

## What is in it

| | |
|---|---|
| `compose.yml` | MariaDB 11.8, two Redis, and the `frappe/bench` image (Python 3.14, Node 24, bench 5.x), pinned by digest |
| `up.ps1`, `down.ps1`, `destroy.ps1`, `shell.ps1`, `exec.ps1` | the commands above |
| `lib.sh`, `bootstrap.sh` | run inside the container; `bootstrap.sh` builds the bench, installs the engine, ERPNext and the app |
| `build-engine-wheel.ps1`, `install-engine.sh` | get the engine into the bench: the one place that knows how (README, "The engine") |
| `gate.sh`, `run-tests.sh`, `semgrep.ps1` | the checks; `gate.sh` audits the engine's dependencies as installed |
| `check-uninstall.sh`, `scripts/snapshot.py`, `scripts/diff_snapshots.py`, `scripts/check_coexistence.py`, `scripts/standalone_fields.py` | the uninstall check, with a site that already has the standalone service's fields |
| `check-upgrade.sh`, `scripts/upgrade_seed.py`, `scripts/upgrade_state.py`, `scripts/check_upgrade_compare.py` | the upgrade check: an earlier version installed and used, then the working tree and `bench migrate`; the compare script lists what is required and says PASS or FAIL for each |
| `verify-all.ps1` | all of it from nothing |
| `roundtrip.ps1`, `browser/round-trip.cjs`, `scripts/seed.py`, `scripts/reset_demo.py` | the end-to-end trial of the placeholder below |
| `telegram-e2e.ps1`, `scripts/telegram_e2e.py`, `scripts/fake_telegram.py`, `scripts/telegram_ui_setup.py`, `browser/telegram-ui.cjs` | the Telegram connection tried without a bot or the internet: a pretend Telegram (`fake_telegram.py`) on a local port, a site that is told to call it, and the walk through it. With a real bot in polling mode, give the development bench two workers for the `long` queue (`bench worker --queue long`, twice): `bench start` runs one worker for every queue, and the polling loop keeps it busy |
| `demo.ps1`, `browser/demo-flow.cjs`, `scripts/seed_demo_flow.py` | the flow of a request on demo data, to follow in the browser: the data, the walkthrough, and (`-Run`) the same walk in the headless browser with the time of each step |
| `images.lock` | the image digests that were really used (written by `up.ps1`) |
| `timings.log` | how long each step took (not in git) |

## Placeholders: replaced in Phase 5

These are the first experiment's, kept so that the app can be tried end to end. They are marked in the code with the words "replaced in Phase 5".

* `ai_munimji/jobs.py` (`check_stock`): the scheduled entry. At the time the Settings page names, and only while Watch stock is ticked, it queues the engine's stock check (`run_stock_check`) on the long queue
  with a timeout of six hours and returns; the run works in batches of 200 items, committing and renewing its lease after each.
* The list **Munimji Approval Request**: its form has one button, "Create Purchase Order", which calls `ai_munimji.api.answer`. Phase 5 builds the approval form with the reasoning, the inbox and
  the notifications.
* `scripts/seed.py`, `scripts/reset_demo.py`, `roundtrip.ps1` and `browser/round-trip.cjs`, which exist for the two above (the demo's requests are made by `reset_demo.py`, which does what the job and
  a person's approval would, so that the round trips do not depend on when the scheduler ticks).

Everything else (settings, roles, fields, uninstall, the engine dependency, the tests that read the code) is the app proper.
