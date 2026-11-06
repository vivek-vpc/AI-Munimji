"""Runs a Python file inside a Frappe site, like `bench console` but from a file, and commits when it finishes.
The script sees `frappe` and `args` (the extra command-line words) as globals.

From the bench directory, inside the container:
    env/bin/python /workspace/ai_munimji/dev/frappe_run.py <site> <script.py> [args...]
Easier from Windows:
    .\\dev\\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/<script>.py [args...]
"""

import runpy
import sys

import frappe


def main():
	site, script, *args = sys.argv[1:]
	frappe.init(site=site)  # run from the bench's sites/ directory, as the bench commands do
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		runpy.run_path(script, init_globals={"frappe": frappe, "args": args})
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


main()
