# What Frappe does with the values the stores write: probes on the real database

Measured on 7 Nov 2026 on the development site (Frappe 16.55.2, ERPNext 16.54.0, MariaDB 11.8, REPEATABLE READ), before the stores were built, by `dev/scripts/probe_stores.py` (it makes two
throw-away DocTypes, prints one report, and removes them). Each line decided something in [STORES.md](STORES.md).

| Question | What was found | What the stores do about it |
|---|---|---|
| A number column given `None` (Float, Int, Currency) | stored and read back as `0.0` / `0`; the column is NOT NULL | a note of which numbers were empty, so `None` and `0.0` come back as two things |
| A Check given `None` | `0` | the engine's Check columns are never empty (a run's `dry_run`, a call's `ok`) |
| A Select given `None` | `''` | no Select columns: statuses are plain text |
| Data, Link, Long Text, Small Text, Datetime, Date given `None` | `None` | as written |
| Data given `''` | `''` | as written (`None` and `''` stay two things) |
| JSON field given valid JSON text | the text, byte for byte (key order, spaces, any language, 2 MB), by `get_doc` and by `get_list` | the engine's JSON columns are JSON fields |
| JSON field given text that is not JSON, or `''` | refused by the database (error 4025, a `json_valid` check) | the engine's JSON columns are always valid JSON or `None`; an absent value is `None` |
| Long Text, Code given the same texts | byte for byte as well | long reasoning text is Long Text |
| A Datetime | `datetime(6)`, returned as a naive `datetime`, with microseconds | a moment is stored as the site's wall clock (docs/STORES.md) |
| Names | collation `utf8mb4_unicode_ci`: `AbC` and `abc` collide (duplicate entry); a filter on a Data field ignores case, accents and trailing spaces; a name longer than 140 characters is refused | ids from outside are named by a hash; the engine's own ids are lowercase hex |
| A unique Data field given a duplicate | `UniqueValidationError` | the audit seal's `prev` is unique, so the chain cannot fork |
| The "autoincrement" naming rule | names are numbers (bigint), but the sequence is not rolled back with a transaction and is not reset when rows are deleted | numbers come from a counter record instead |
| Savepoints | `frappe.db.savepoint` and `rollback(save_point=...)` undo exactly what was done since | the unit of work (`CoreStores.transaction`) is a savepoint |
| `get_list` with aggregate fields as strings | refused; the dict form `{"COUNT": "name", "as": "n"}` works | counts use the dict form |
| The isolation level | `REPEATABLE-READ`, `innodb_lock_wait_timeout` 50 s, `innodb_snapshot_isolation` OFF (as dev/compose.yml and Frappe's own Docker files set it) | see the next two lines; with `innodb_snapshot_isolation` ON (the stock image's value, found by the first GitHub run on 9 Nov 2026) a locking read of a row another connection changed since the transaction began fails with error 1020, so the overlapping-work tests fail (6 of 10) — the setting is a requirement in [INSTALL.md](INSTALL.md) |
| A connection that has already read something, asked for a row another connection committed since | a plain `get_list` does not see it; `get_doc(for_update=True)` and `db.get_value(for_update=True)` do | the look for an existing order is a locking read |
| `get_doc(for_update=True)` on a row another connection holds | waits for that connection to commit (measured: 2.0 s for a 2 s hold) | the row lock |
| Two connections inserting the same name | the second waits for the first's commit, then gets `DuplicateEntryError` | `claim(channel, id)` is an insert, and the error is its `False` |
