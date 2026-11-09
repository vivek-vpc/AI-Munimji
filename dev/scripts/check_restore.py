"""Checks a site that was restored from a backup of a site that ran AI Munimji (docs/BACKUP_RESTORE.md): the records are there, the audit seal verifies, a pending request can still be answered,
and the stock check's job is still stopped until Watch stock is switched on. It prints the numbers it found, then PASS or FAIL for each check, then ALL OK or FAILED. It leaves the site as it found
it (everything it does is rolled back).

    SITE=<restored site> bash dev/run-script.sh dev/scripts/check_restore.py     (in the dev container: .\\dev\\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh ...)
"""

import json
import sys

import frappe

from ai_munimji import api, jobs, schedule

REQUEST = "Munimji Approval Request"
SETTINGS = "AI Munimji Settings"
APPROVER = "munimji.approver@example.com"  # the dev site's approver (dev/scripts/seed.py)
results: list[bool] = []


def check(ok, what: str) -> None:
	print(("  PASS  " if ok else "  FAIL  ") + what)
	results.append(bool(ok))


frappe.set_user("Administrator")
by_status = {
	r.status: r.n
	for r in frappe.get_all(REQUEST, fields=["status", {"COUNT": "name", "as": "n"}], group_by="status")
}
numbers = {
	"requests_by_status": by_status,
	"proposals": frappe.db.count("Munimji Purchase Proposal"),
	"work_orders": frappe.db.count("Munimji Work Order"),
	"audit_seal_rows": frappe.db.count("Munimji Audit Seal"),
	"watch_stock": frappe.db.get_single_value(SETTINGS, "enabled"),
	"check_cron": frappe.db.get_single_value(SETTINGS, "check_cron"),
}
print("FOUND " + json.dumps(numbers, sort_keys=True))

check(
	by_status.get("pending", 0) >= 1 and by_status.get("decided", 0) >= 1,
	"requests are there, some answered and some pending",
)
check(
	numbers["proposals"] >= 1 and numbers["work_orders"] >= 1,
	"the purchase proposals and work orders are there",
)

verdict = jobs.system_services().audit.verify()
check(
	verdict.get("ok") and verdict.get("entries", 0) >= 1,
	f"the audit seal verifies ({verdict.get('entries')} entries)",
)

job = frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD})
check(
	job.stopped == 1 and not numbers["watch_stock"],
	"the stock check's job is still stopped and Watch stock is still off",
)
check(
	frappe.db.count("Scheduled Job Type", {"method": schedule.METHOD}) == 1
	and frappe.db.count("Scheduler Event", {"method": schedule.METHOD}) == 1
	and frappe.db.count("Notification", {"document_type": REQUEST}) == 1,
	"one job, one Scheduler Event and one notification (nothing doubled by the restore)",
)

pending = frappe.get_all(
	REQUEST, filters={"status": "pending", "kind": "procurement.po"}, pluck="name", order_by="creation asc"
)
if pending:
	frappe.set_user(APPROVER)
	answered = api.answer(pending[0], "approve")
	check(
		answered.get("ok"),
		f"a pending request can be answered by the approver: {str(answered.get('message'))[:70]}",
	)
	again = api.answer(pending[0], "approve")
	check(not again.get("ok"), "and a second press is refused")
	frappe.set_user("Administrator")
else:
	check(False, "there is a pending purchase request to answer")

page = frappe.get_doc(SETTINGS)
page.enabled = 1
page.save()
check(
	frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD}).stopped == 0,
	"switching Watch stock on starts the job",
)

frappe.db.rollback()  # the site is left as it was restored
print("\nALL OK" if all(results) else "\nFAILED")
sys.exit(0 if all(results) else 1)
