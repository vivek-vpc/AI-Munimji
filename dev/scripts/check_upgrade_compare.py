"""Used by dev/check-upgrade.sh: compares the state of a site before and after an upgrade, and after a second `bench migrate`, and says PASS or FAIL for each thing the release notes claim.

    python3 dev/scripts/check_upgrade_compare.py before.json after.json again.json

Exit code 1 if any claim fails. Pure Python: it reads the three files and nothing else.
"""

import json
import sys

before, after, again = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:4])
failed = 0


def claim(text: str, ok: bool, detail: str = "") -> None:
	global failed
	print(f"  {'PASS' if ok else 'FAIL'}  {text}" + ("" if ok or not detail else f"  ({detail})"))
	failed += 0 if ok else 1


claim(
	"the code really changed version",
	before["version"] != after["version"],
	f"{before['version']} -> {after['version']}",
)

# what a person had set stays as they set it (a setting the old version had no field for is not compared)
kept = {k: v for k, v in before["settings"].items() if v is not None}
changed = {k: (v, after["settings"].get(k)) for k, v in kept.items() if after["settings"].get(k) != v}
claim("the settings the person had are unchanged", not changed, str(changed))

# the stock check's job, its schedule and whether it runs, are as they were
old_jobs = {m: j for m, j in before["jobs"].items()}
moved = {m: (j, after["jobs"].get(m)) for m, j in old_jobs.items() if after["jobs"].get(m) != j}
claim(
	"every job that existed has the same schedule and the same stopped / running state", not moved, str(moved)
)

# nothing is switched on by the upgrade
claim("Telegram is off after the upgrade", not after["settings"].get("telegram_enabled"))
telegram_job = after["jobs"].get("ai_munimji.telegram.jobs.housekeeping")
claim(
	"the Telegram housekeeping job exists and is stopped",
	telegram_job is not None and telegram_job["stopped"] == 1,
	str(telegram_job),
)
claim(
	"the Telegram link DocType and its table exist",
	"Munimji Telegram Link" in after["doctypes"] and after["telegram_link_table"],
)

# nothing the old version had is lost
claim(
	"every DocType of the old version is still there",
	set(before["doctypes"]) <= set(after["doctypes"]),
	str(sorted(set(before["doctypes"]) - set(after["doctypes"]))),
)
claim(
	"the three roles, the seven fields and the notification are still there",
	(before["roles"], before["custom_fields"], before["notifications"])
	== (after["roles"], after["custom_fields"], after["notifications"]),
)
claim(
	"the requests of the old version are still there",
	after["approval_requests"] >= before["approval_requests"],
)
claim(
	"every Scheduler Event of the old version is still there",
	set(before["scheduler_events"]) <= set(after["scheduler_events"]),
)

# a second migrate changes nothing
claim("a second `bench migrate` changes nothing", after == again)

print("ALL OK" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
