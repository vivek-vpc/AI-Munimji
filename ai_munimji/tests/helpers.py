import frappe

# README of the standalone service: to create a Purchase Order in ERPNext a person needs Purchase User AND Purchase Manager.
APPROVER_ROLES = ("Munimji Approver", "Purchase User", "Purchase Manager")


def make_user(email: str, roles: tuple[str, ...]) -> str:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": 1,
			"roles": [{"role": role} for role in roles],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


def make_request(title: str = "Reorder", **facts):
	"""A pending purchase request, made as the engine makes one (through the approval store, in the named system mode: run it as Administrator). `facts` are the request's facts."""
	import json

	from ai_munimji.stores import frappe_core_stores

	request = {
		"kind": "procurement.po",
		"title": title,
		"facts": {
			"item_code": "_Test Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 10,
			"supplier": "_Test Supplier",
			**facts,
		},
	}
	request_id = frappe.generate_hash(length=10)
	frappe_core_stores(system=True).approvals.insert(
		request_id,
		"procurement.po",
		json.dumps(request),
		"procurement_proposal",
		request_id,
		"2026-10-16T08:00:00+00:00",
		None,
	)
	return frappe.get_doc("Munimji Approval Request", request_id)


def empty_store_tables() -> None:
	"""Empty every DocType of the engine's stores, then make the lock rows again (the numbers start again at 1). A test does this inside its own transaction and rolls back, so a site that
	holds records is not touched; one that commits (the parallel and end-to-end tests) empties the tables again when it is done."""
	from ai_munimji.stores import locks
	from ai_munimji.stores.specs import TABLES

	for table in TABLES:
		frappe.db.delete(table.doctype)
	locks.ensure()


def insert_sealed_history(count: int, chunk: int = 2000, progress=None) -> None:
	"""`count` closed requests, each sealed, in a valid chain, into the empty store tables: what a site holds after a long time. Raw SQL, because the document API would take hours (tests and
	dev/scripts/seed_audit.py only: the app never writes like this). Each request is as the engine keeps one, so that `AuditChain.verify()` passes over it. The flag the sweep looks at
	(`sealed`) is set on each."""
	import json
	from datetime import UTC, datetime, timedelta

	from ai_munimji_engine.core.audit import GENESIS, approval_payload, digest, link

	from ai_munimji.stores import locks
	from ai_munimji.stores.core import Context

	ctx = Context()
	approvals, seal = ctx.table("approvals"), ctx.table("audit_chain")
	assert not frappe.db.count(approvals.doctype) and not frappe.db.count(seal.doctype), (
		"the store tables must be empty"
	)
	stamp_columns = ("creation", "modified", "modified_by", "owner", "docstatus", "idx")
	flagged = (
		{"sealed": 1} if frappe.db.has_column(approvals.doctype, "sealed") else {}
	)  # a site that has not been migrated to the flag yet is seeded without it

	def insert(table, rows):
		names = list(rows[0])
		frappe.db.bulk_insert(table.doctype, names, [tuple(r[n] for n in names) for r in rows])

	prev, base = GENESIS, datetime(2026, 1, 1, tzinfo=UTC)
	for low in range(0, count, chunk):
		approval_rows, seal_rows = [], []
		for i in range(low, min(low + chunk, count)):
			created = (base + timedelta(minutes=5 * i)).isoformat()
			decided = (base + timedelta(minutes=5 * i + 3)).isoformat()
			request = {
				"kind": "inventory.reorder",
				"title": f"Reorder SC-{i:06d}",
				"severity": "HIGH",
				"facts": {"item_code": f"SC-{i % 30000 + 1:06d}", "warehouse": "Stores - MDC", "qty": 10},
			}
			row = {
				"id": f"SEED-{i:07d}",
				"kind": "inventory.reorder",
				"status": "decided",
				"request_json": json.dumps(request),
				"decision_json": json.dumps(
					{"action": "approve", "actor_id": "munimji.approver@example.com", "channel": "desk"}
				),
				"ref_type": None,
				"ref_id": None,
				"created_at": created,
				"expires_at": None,
				"decided_at": decided,
				"last_reminder_at": None,
				"reminder_count": 0,
				"status_note": None,
			}
			stamp = dict(
				zip(
					stamp_columns,
					(decided[:19].replace("T", " "),) * 2 + ("Administrator", "Administrator", 0, 0),
					strict=True,
				)
			)
			approval_rows.append({"name": row["id"], **approvals.values(row), **stamp, **flagged})
			d = digest(approval_payload(row))
			at = (base + timedelta(minutes=5 * i + 4)).isoformat()
			event = "sealed" if i == 0 else "decided"
			h = link(prev, "approval", row["id"], event, at, d)
			entry = {
				"seq": i + 1,
				"at": at,
				"source": "approval",
				"ref_id": row["id"],
				"event": event,
				"digest": d,
				"prev": prev,
				"hash": h,
			}
			seal_rows.append({"name": str(i + 1), **seal.values(entry), **stamp})
			prev = h
		insert(approvals, approval_rows)
		insert(seal, seal_rows)
		if progress:
			progress(min(low + chunk, count))
	frappe.db.sql(
		"UPDATE `tabMunimji Lock` SET counter = %s WHERE name = %s", (count, locks.counter_name(seal.doctype))
	)


class FakeStock:
	"""A stock for the stock check to read without ERPNext (tests only): `count` items, FS-000 ..., of which those whose number is in `low` hold 1 and the rest 500, each used one a day for
	the last 60 days. Only the reads the inventory agent makes; nothing that makes a document."""

	system = True

	def __init__(self, count: int, low=()):
		self.codes = [f"FS-{i:03d}" for i in range(count)]
		self.low = {self.codes[i] for i in low}

	def healthcheck(self) -> bool:
		return True

	def list_items(self):
		from datetime import date, timedelta

		from ai_munimji_engine.packs.stock_procurement.erp import ItemInfo

		created = date.today() - timedelta(days=400)
		return [
			ItemInfo(code=c, name=c, group="Fake", uom="Nos", lead_time_days=7.0, created=created)
			for c in self.codes
		]

	def get_stock(self, item_codes, warehouses=None):
		from ai_munimji_engine.packs.stock_procurement.erp import StockInfo

		return {c: StockInfo(on_hand=1.0 if c in self.low else 500.0) for c in item_codes}

	def get_consumption(self, item_codes, start, end, warehouses=None):
		from datetime import timedelta

		from ai_munimji_engine.packs.stock_procurement.erp import DailyUsage

		return {c: [DailyUsage(end - timedelta(days=k), 1.0) for k in range(1, 61)] for c in item_codes}

	def get_vendor_offers(self, item_code, since, quotes=None):
		from datetime import date, timedelta

		from ai_munimji_engine.packs.stock_procurement.erp import VendorOffer

		return [
			VendorOffer(
				supplier="FS-SUPPLIER",
				name="A fake supplier",
				unit_price=5.0,
				avg_price=5.0,
				lead_time_days=5.0,
				on_time_rate=0.9,
				orders=3,
				last_order=date.today() - timedelta(days=30),
				listed=True,
				currency="INR",
			)
		]

	def get_purchase_taxes(self, supplier, item_code, posting_date):
		from ai_munimji_engine.packs.stock_procurement.erp import TaxSetup

		return TaxSetup(template=None, source="none")
