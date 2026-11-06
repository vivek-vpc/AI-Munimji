"""Scenario E of dev/check-uninstall.sh: a site where the standalone service's fields exist first. Reads four snapshots and prints PASS or FAIL for each statement.
    python3 check_coexistence.py E0.json E1.json E2.json E3.json
E0 = after the service's `erp-setup`; E1 = after the app is installed; E2 = after it is uninstalled; E3 = after `erp-setup` again.
"""

import json
import sys

e0, e1, e2, e3 = (json.load(open(p)) for p in sys.argv[1:5])
failed = 0


def check(ok, what):
	global failed
	print(f"  {'PASS' if ok else 'FAIL'}  {what}")
	failed += 0 if ok else 1


seven = sorted(e0["custom_fields"])
check(len(seven) == 7, f"the service's erp-setup made seven fields ({len(seven)})")
check(e1["custom_fields"] == seven, "installing the app finds them and adds no eighth: the same seven names")
check(
	e0["custom_columns"] == e1["custom_columns"] == e2["custom_columns"] == e3["custom_columns"],
	"no column was made or dropped by installing, uninstalling or erp-setup again",
)
check(
	all(
		v == "Agent proposal reference" or v == "Approved by (Stock Assistant)" or v == "Stock Assistant note"
		for v in e0["custom_field_labels"].values()
	),
	"before the app the labels are the service's",
)
check(
	set(e1["custom_field_labels"].values()) == {"Munimji request", "Approved by (Munimji)", "Munimji note"},
	"after the app is installed the labels are the app's (the app owns the records now; the names and the columns are the same)",
)
check(
	e1["indexes_on_the_reference"] == e0["indexes_on_the_reference"],
	"the index on the reference is the same, and not unique: " + json.dumps(e1["indexes_on_the_reference"]),
)
check(
	e2["custom_fields"] == [],
	"uninstalling the app removes the seven records (the service would report that its fields are missing)",
)
check(e3["custom_fields"] == seven, "erp-setup again makes them again, on the columns that stayed")
check(
	e3["custom_field_labels"] == e0["custom_field_labels"],
	"and they are the service's again, as they were before the app",
)
sys.exit(1 if failed else 0)
