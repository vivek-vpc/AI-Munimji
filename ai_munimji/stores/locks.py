"""Row locks, through the document API.

A file lock holds only on the server it was taken on, and it is released when the code leaves the block, which is before the request commits: the next press can then look, find
nothing yet (the first one's order is not committed) and make a second. A lock that is a row of the database is held until the transaction ends, on every worker and every server that
shares the database. That is what these functions give:

  * `take(doctype)`: the one Lock record for making documents of that type, locked until the transaction ends. A second connection that takes it waits for the first to commit or roll
    back, in turn. Making an order is something a person does a few times a day, so one record per document type costs nothing, and it avoids the two failures that finer locks had when
    five presses (and then two different references) were pressed together: a record made on demand deadlocks (each connection holds a shared lock on the duplicate and asks for the
    exclusive one), and a locking read of a reference that has no order yet takes a gap lock that two different references' inserts then wait on. The records are made at install and
    migrate (`ensure()`); reading one for update needs no right on the Lock DocType, so a person with only the ERPNext role can still make the document.
  * `find_locked(doctype, filters)`: the name of the newest document that matches, read with a locking read. MariaDB's default isolation level (REPEATABLE READ) lets a plain read miss
    what another connection committed after this one's first read; a locking read always sees it, which is how the second press learns what the first made. It returns a name and
    nothing else; the caller reads the document through the permission rules.
  * `next_number(doctype)`: 1, 2, 3 ... for the tables whose rows the engine numbers. The counter is a Lock record too, so it is rolled back with the transaction (a database sequence
    would not be) and two connections never get the same number.
  * `lease(name, holder, minutes)` / `release(name, holder)`: "one scheduled run at a time" that survives a worker that dies: the lease expires. `renew(name, holder, minutes)` moves the end
    of a lease the run still holds, at the end of each batch of a long run, and says `LeaseLost` if another run has taken it in the meantime. `held(name)` says whether somebody holds one now.
"""

import hashlib
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from ai_munimji.stores import missing
from ai_munimji.stores.specs import TABLES

LOCK = "Munimji Lock"
MAKING = ("Purchase Order", "Material Request", "Stock Entry")  # the documents the app makes from a request
LEASES = ("stock_check", "telegram_poll", "telegram_outbox")


def _hash(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def mutex_name(doctype: str) -> str:
	return f"making-{_hash(doctype)}"


def counter_name(doctype: str) -> str:
	return f"number-{_hash(doctype)}"


def lease_name(name: str) -> str:
	return f"lease-{_hash(name)}"


def names() -> list[str]:
	"""Every Lock record the app expects to exist."""
	return (
		[mutex_name(d) for d in MAKING]
		+ [counter_name(t.doctype) for t in TABLES if t.numbered]
		+ [lease_name(n) for n in LEASES]
	)


def _row(name: str, for_update: bool = True):
	try:
		return frappe.get_doc(LOCK, name, for_update=for_update)
	except frappe.DoesNotExistError:
		missing.not_there()
		return None


def _make(name: str):
	doc = frappe.get_doc({"doctype": LOCK})
	doc.flags.name_set = True
	doc.flags.munimji_store = True
	doc.name = name
	return doc.insert()


def ensure() -> int:
	"""Make the Lock records that are missing (install and migrate call this; running it again changes nothing). Returns how many were made."""
	made = 0
	for name in names():
		if _row(name, for_update=False) is None:
			_make(name)
			made += 1
	return made


def _take_row(name: str):
	doc = _row(name)
	if doc is None:  # a site that was not migrated: make it (a rare, one-time race is the lesser evil)
		try:
			return _make(name)
		except frappe.DuplicateEntryError:
			doc = _row(name)
	return doc


def take(doctype: str):
	"""The Lock record for making documents of this type, locked for update until this transaction commits or rolls back."""
	return _take_row(mutex_name(doctype))


def find_locked(doctype: str, filters: dict, order_by: str = "creation desc") -> str | None:
	"""The name of the newest document of this type that matches the filters, found with a locking read (see above), or None."""
	return frappe.db.get_value(doctype, filters, "name", order_by=order_by, for_update=True)


def next_number(doctype: str) -> int:
	lock = _take_row(counter_name(doctype))
	lock.counter = int(lock.counter or 0) + 1
	lock.flags.munimji_store = True
	lock.save()
	return lock.counter


def lease(name: str, holder: str, minutes: float) -> bool:
	"""Take the lease called `name` for `minutes` if nobody holds it (or its holder's time has run out). Commits at once, so that whoever asks next sees it: take a lease before doing
	anything else in a job. True when the caller has it now."""
	if frappe.db.transaction_writes:
		raise RuntimeError(
			"take a lease first: it commits, and this transaction already has uncommitted work"
		)
	row = _take_row(lease_name(name))
	now = now_datetime()
	if row.holder and row.holder != holder and row.until and row.until > now:
		frappe.db.rollback()
		return False
	row.holder, row.until = holder, now + timedelta(minutes=minutes)
	row.flags.munimji_store = True
	row.save()
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - a lease nobody else can see is no lease: the commit is the point
	return True


def held(name: str) -> bool:
	"""Whether somebody holds the lease `name` now (it has an owner whose time has not run out). A look only: it takes nothing and locks nothing."""
	row = _row(lease_name(name), for_update=False)
	return bool(row and row.holder and row.until and row.until > now_datetime())


class LeaseLost(RuntimeError):
	"""The lease this run held now belongs to another run: this one was away for longer than the lease lasts, and must stop."""


def renew(name: str, holder: str, minutes: float) -> None:
	"""Move the end of the lease `name` to `minutes` from now. It does not commit: the caller commits with what it has written, so that the renewal and the work it vouches for are
	kept together. Raises LeaseLost when `holder` no longer holds it (it expired and another run took it)."""
	row = _take_row(lease_name(name))
	if row.holder != holder:
		raise LeaseLost(f"the lease {name} is held by {row.holder or 'nobody'} now, not by {holder}")
	row.until = now_datetime() + timedelta(minutes=minutes)
	row.flags.munimji_store = True
	row.save()


def release(name: str, holder: str) -> None:
	row = _take_row(lease_name(name))
	if row.holder == holder:
		row.holder, row.until = None, None
		row.flags.munimji_store = True
		row.save()
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - the next tick must see that the lease is free
