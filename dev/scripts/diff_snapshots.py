"""Compares two snapshots (JSON written by snapshot.py) and prints every difference. Exit code 1 if they differ.
    python3 diff_snapshots.py <from.json> <to.json>
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


a, b = load(sys.argv[1]), load(sys.argv[2])
different = 0
for key in sorted(set(a) | set(b)):
	if a.get(key) == b.get(key):
		continue
	different += 1
	va, vb = a.get(key), b.get(key)
	if isinstance(va, list) and isinstance(vb, list):
		print(f"  {key}: removed {sorted(set(va) - set(vb))} | added {sorted(set(vb) - set(va))}")
	else:
		print(f"  {key}: {va!r} -> {vb!r}")
print("same" if not different else f"{different} difference(s)")
sys.exit(1 if different else 0)
