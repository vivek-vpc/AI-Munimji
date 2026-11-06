"""Compares two snapshots (JSON written by snapshot.py) and prints every difference. Exit code 1 if they differ in a way that is not allowed.
    python3 diff_snapshots.py <from.json> <to.json> [--allow key,key,...]
`--allow` names keys (as printed, for example `custom_columns.Purchase Order`) or the start of a key (`custom_columns`): a difference there is printed as "allowed" and does not fail.
"""

import json
import sys


def flatten(prefix, value, out):
	if isinstance(value, dict):
		for key, item in value.items():
			flatten(f"{prefix}.{key}" if prefix else key, item, out)
	else:
		out[prefix] = value


def load(path):
	out = {}
	with open(path) as f:
		flatten("", json.load(f), out)
	return out


args = sys.argv[1:]
allowed = []
if "--allow" in args:
	at = args.index("--allow")
	allowed = [a for a in args[at + 1].split(",") if a]
	args = args[:at] + args[at + 2 :]
a, b = load(args[0]), load(args[1])
unexpected = 0
for key in sorted(set(a) | set(b)):
	if a.get(key) == b.get(key):
		continue
	va, vb = a.get(key), b.get(key)
	ok = any(key == p or key.startswith(p + ".") for p in allowed)
	mark = "  (allowed)" if ok else ""
	if not ok:
		unexpected += 1
	if isinstance(va, list) and isinstance(vb, list):
		as_text = lambda items: {json.dumps(i, sort_keys=True) for i in items}  # noqa: E731 - the items may themselves be lists
		print(
			f"  {key}: removed {sorted(as_text(va) - as_text(vb))} | added {sorted(as_text(vb) - as_text(va))}{mark}"
		)
	else:
		print(f"  {key}: {va!r} -> {vb!r}{mark}")
print(
	"same"
	if not (a != b)
	else ("only allowed differences" if not unexpected else f"{unexpected} unexpected difference(s)")
)
sys.exit(1 if unexpected else 0)
