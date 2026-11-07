"""Row locks, through the document API.

A file lock holds only on the server it was taken on, and it is released when the code leaves the block, which is before the request commits: the next press can then look, find
nothing yet (the first one's order is not committed) and make a second. A lock that is a row of the database is held until the transaction ends, on every worker and every server that
shares the database. That is what these functions give:

  * `take(key)`: a Lock record chosen by the key, locked until the transaction ends. A second connection that takes the same record waits for the first to commit or roll back, in turn.
    There is a fixed set of 64 records (made at install and migrate, `ensure()`), and a key picks one by its hash: two different keys may share one, which only makes them wait for each
    other a moment. They are never made on demand in a person's session: two connections that find a missing row and each INSERT it end up holding a shared lock apiece on the duplicate
    and deadlock when they ask for the exclusive one (found with five presses at once).
  * `marker(key)`: under that lock, the record that remembers what the key led to. MariaDB's default isolation level (REPEATABLE READ) lets a plain read miss what another connection
    committed after this one's first read; a locking read always sees it, which is how the second press learns what the first made.
  * `next_number(doctype)`: 1, 2, 3 ... for the tables whose rows the engine numbers. The counter is a Lock record too, so it is rolled back with the transaction (a database sequence
    would not be) and two connections never get the same number.
  * `lease(name, holder, minutes)` / `release(name, holder)`: "one scheduled run at a time" that survives a worker that dies: the lease expires.
"""

import hashlib
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from ai_munimji.stores import convert
from ai_munimji.stores.specs import TABLES

LOCK = "Munimji Lock"
STRIPES = 64


def stripe_name(key: str) -> str:
	return f"ref-{int(hashlib.sha256(key.encode('utf-8')).hexdigest(), 16) % STRIPES:02d}"


def counter_name(doctype: str) -> str:
	return "number-" + hashlib.sha256(doctype.encode("utf-8")).hexdigest()[:12]


def names() -> list[str]:
	"""Every Lock record the app expects to exist."""
	return [stripe_name_at(i) for i in range(STRIPES)] + [
		counter_name(t.doctype) for t in TABLES if t.numbered
	]


def stripe_name_at(i: int) -> str:
	return f"ref-{i:02d}"


def _row(name: str, for_update: bool = True):
	try:
		return frappe.get_doc(LOCK, name, for_update=for_update)
	except frappe.DoesNotExistError:
		return None


def _make(name: str):
	doc = frappe.get_doc({"doctype": LOCK})
	doc.flags.name_set = True
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


def take(key: str):
	"""The Lock record for `key`, locked for update until this transaction commits or rolls back."""
	return _take_row(stripe_name(key))


def marker(key: str):
	"""The record that remembers what a key led to (`result`: the name of the order made for a reference). Take the stripe lock for the same key first: then one connection at a time
	makes or reads it. It is made by INSERT and, if it exists, read with a locking read; a locking read of a row that is not there takes a gap lock, and two references whose rows would
	sit in the same gap then each wait for the other's insert (found with two different references pressed together)."""
	name = convert.hashed_name(key)
	doc = frappe.get_doc({"doctype": LOCK})
	doc.flags.name_set = True
	doc.name = name
	try:
		return doc.insert()
	except frappe.DuplicateEntryError:
		return frappe.get_doc(LOCK, name, for_update=True)


def next_number(doctype: str) -> int:
	lock = _take_row(counter_name(doctype))
	lock.counter = int(lock.counter or 0) + 1
	lock.save()
	return lock.counter


def lease(name: str, holder: str, minutes: float) -> bool:
	"""Take the lease called `name` for `minutes` if nobody holds it (or its holder's time has run out). Commits at once, so that whoever asks next sees it: take a lease before doing
	anything else in a job. True when the caller has it now."""
	if frappe.db.transaction_writes:
		raise RuntimeError(
			"take a lease first: it commits, and this transaction already has uncommitted work"
		)
	row = _take_row(f"lease-{counter_name(name)[7:]}")
	now = now_datetime()
	if row.holder and row.holder != holder and row.until and row.until > now:
		frappe.db.rollback()
		return False
	row.holder, row.until = holder, now + timedelta(minutes=minutes)
	row.save()
	frappe.db.commit()
	return True


def release(name: str, holder: str) -> None:
	row = _take_row(f"lease-{counter_name(name)[7:]}")
	if row.holder == holder:
		row.holder, row.until = None, None
		row.save()
	frappe.db.commit()
