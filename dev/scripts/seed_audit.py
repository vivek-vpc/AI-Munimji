# Fills a SCALE site (never the development site) with closed requests that are all sealed, in a valid chain, for the audit-sweep measurement of the production-readiness review.
# Raw SQL, on purpose: 200,000 requests through the document API would take hours, and this script is not part of the app (tests/test_rules.py reads only the app's package).
#   cd /workspace/ai_munimji && SITE=scale.localhost bash dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_audit.py 200000
# Existing requests and seal entries are deleted first. Each request is as the engine keeps one (the same text the seal digests), so `AuditChain.verify()` passes on it. The writer is the
# test helper `insert_sealed_history`, loaded by its path so that it also seeds a site whose code is older than the flag it sets.
import importlib.util
import time

assert frappe.local.site.startswith("scale"), f"{frappe.local.site} is not a scale site"
from ai_munimji.stores import frappe_core_stores
from ai_munimji.stores.core import Context

spec = importlib.util.spec_from_file_location(
	"seed_helpers", "/workspace/ai_munimji/ai_munimji/tests/helpers.py"
)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)

N = int(args[0]) if args else 200000
db = frappe.db
ctx = Context()
approvals, seal = ctx.table("approvals"), ctx.table("audit_chain")
for doctype in (approvals.doctype, seal.doctype):
	db.sql(f"TRUNCATE TABLE `tab{doctype}`")
db.commit()
start = time.time()
helpers.insert_sealed_history(
	N,
	progress=lambda done: print(f"  {done:,} of {N:,}: {time.time() - start:.0f} s", flush=True)
	if done % 20000 == 0
	else None,
)
db.commit()
db.sql(f"ANALYZE TABLE `tab{approvals.doctype}`, `tab{seal.doctype}`")
print(
	f"{N:,} sealed requests written in {time.time() - start:.0f} s; flag column present: {db.has_column(approvals.doctype, 'sealed')}"
)
print(
	"last hash:",
	frappe_core_stores(system=True).audit.last_hash()[:16],
	"| seal rows:",
	db.sql(f"SELECT COUNT(*) FROM `tab{seal.doctype}`")[0][0],
)
