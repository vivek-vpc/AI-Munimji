"""The unit of work all the stores of one bundle share (`CoreStores.transaction`).

Frappe's request or job owns the database transaction and commits it when it ends. The engine asks for a smaller unit inside it: "this decision, with what its handler wrote, all or nothing".
That is a savepoint: the outermost use takes one and rolls back to it if the block raises; a block inside another joins it (the engine's rule, and the SQLite store's).
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe


@contextmanager
def transaction() -> Iterator[None]:
	depth = getattr(frappe.local, "munimji_unit_depth", 0)
	if depth:
		frappe.local.munimji_unit_depth = depth + 1
		try:
			yield
		finally:
			frappe.local.munimji_unit_depth = depth
		return
	savepoint = f"munimji_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(savepoint)
	frappe.local.munimji_unit_depth = 1
	try:
		yield
	except BaseException:
		frappe.db.rollback(save_point=savepoint)
		raise
	finally:
		frappe.local.munimji_unit_depth = 0
