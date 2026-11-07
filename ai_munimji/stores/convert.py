"""Between the engine's rows and Frappe's fields: ISO text and Datetime, JSON text and JSON fields, names.

The engine writes every moment as ISO-8601 text in UTC with an offset ("2026-10-16T08:00:00+00:00") and compares them as text. A Frappe Datetime holds the wall clock of the site's time zone
(System Settings), as Frappe's own `creation` and `modified` do, so that the Desk shows and filters it the way people read it. This module turns one into the other and back:

  * out of Frappe: the wall clock is read in the site's time zone and written as UTC text with `+00:00`, with a fraction of a second only when there is one (what the engine writes);
  * into Frappe: an offset is honoured, text without one is taken as UTC.

So what the engine wrote comes back unchanged; what came with another offset comes back as the same moment in UTC. The one thing a wall clock cannot say is which of the two passes of
the hour at the end of daylight saving time a moment belongs to: the first pass is chosen (tests/test_store_convert.py shows it).
"""

import hashlib
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_system_timezone

NAME_LENGTH = 140


def site_zone() -> ZoneInfo:
	return ZoneInfo(get_system_timezone())


def to_datetime(text: str | None, zone: ZoneInfo | None = None) -> datetime | None:
	"""The engine's moment as the site's wall clock (a naive datetime), or None for nothing."""
	if text is None or text == "":
		return None
	moment = datetime.fromisoformat(text)
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=UTC)
	return moment.astimezone(zone or site_zone()).replace(tzinfo=None)


def from_datetime(value: datetime | str | None, zone: ZoneInfo | None = None) -> str | None:
	"""A Datetime field's value as the engine's UTC text."""
	if value is None or value == "":
		return None
	if isinstance(value, str):
		value = datetime.fromisoformat(value)
	return value.replace(tzinfo=zone or site_zone()).astimezone(UTC).isoformat()


def to_date(text: str | None) -> date | None:
	if text is None or text == "":
		return None
	return date.fromisoformat(text)


def from_date(value: date | datetime | str | None) -> str | None:
	if value is None or value == "":
		return None
	if isinstance(value, datetime):
		return value.date().isoformat()
	if isinstance(value, str):
		return date.fromisoformat(value[:10]).isoformat()
	return value.isoformat()


def row_json(row: dict) -> str:
	"""The whole engine row as JSON text (for the tables that keep it whole). Compact, and readable in the database."""
	return json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)


def clip(text: str | None, length: int = NAME_LENGTH) -> str | None:
	"""A copy of a value for a 140-character column; the exact value lives elsewhere (the JSON row), so a longer one is cut."""
	if text is None:
		return None
	text = str(text)
	return text if len(text) <= length else text[: length - 1] + "…"


def hashed_name(*parts: object) -> str:
	"""The name of a record whose key comes from outside (a message id, a cache key, a scope) or is made of several columns. Lowercase hex, so the database's case-insensitive
	comparison cannot make two different keys one, and no key can be too long or hold a character a name may not."""
	material = "\x1f".join("" if p is None else str(p) for p in parts)
	return hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def plain_name(value: object) -> str:
	"""The name for a key the engine or ERPNext made (an id, a Purchase Order number)."""
	name = str(value)
	if not name or name != name.strip() or len(name) > NAME_LENGTH or "<" in name or ">" in name:
		raise ValueError(f"{name[:40]!r} cannot be the name of a record")
	return name


def like_pattern(text: str) -> str:
	"""`text` as the middle of a LIKE pattern in which % and _ and \\ mean themselves."""
	return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
