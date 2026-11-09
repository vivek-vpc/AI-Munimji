import frappe
from frappe import _


def snapshot_isolation_is_on() -> bool | None:
	"""Is MariaDB running with innodb_snapshot_isolation ON? True or False; None when it cannot be told (another database, a statement the account may not run): the callers then say
	nothing and carry on.

	With it ON, a locking read of a row that another connection changed since the transaction began is refused (error 1020), so two people answering one request at the same moment do
	not wait for each other (docs/INSTALL.md). The app cannot change the server, so it only says so. The one statement is fixed and read-only, written out in full: tests/test_rules.py
	allows raw SQL in this module and nowhere else, and only as one literal string."""
	if getattr(frappe.db, "db_type", None) != "mariadb":
		return None
	try:
		rows = frappe.db.sql("SHOW VARIABLES LIKE 'innodb_snapshot_isolation'")
	except Exception:
		return None
	if not rows:
		return None
	return str(rows[0][1]).upper() in ("ON", "1")


def warning() -> str:
	return _(
		"The database has innodb_snapshot_isolation switched ON. When two people answer the same request at the same moment, the second one is not made to wait: that answer is refused, and the person is asked to look again. Set innodb_snapshot_isolation = OFF in the database server's configuration (Frappe's own Docker files do) and restart the server."
	)
