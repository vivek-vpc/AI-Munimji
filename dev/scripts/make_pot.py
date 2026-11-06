# Makes locale/main.pot with Frappe v16's own extractor (frappe.gettext.translate.generate_pot, the function behind `bench generate-pot-file --app ai_munimji`).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/make_pot.py
#
# Why not `bench generate-pot-file --app ai_munimji` itself: in this development bench the app is a soft link to the repository (get-app --soft-link, so that edits made on Windows
# show at once). Frappe's navbar extractor, which reads every hooks.py, turns the file's path into a module name by taking the path relative to the bench folder and dropping the first
# two parts (apps/<app>/), so a hooks.py outside the bench stops it with "is not in the subpath of the bench". An app installed the usual way, under apps/, does not meet this.
# Here that one step is given the repository's own layout; the extraction itself is Frappe's.
import importlib
from pathlib import Path

import frappe.gettext.extractors.navbar as navbar
from frappe.gettext.translate import generate_pot

REPOSITORY = Path("/workspace/ai_munimji")  # where apps/ai_munimji points


def get_module(path):
	relative = Path(path).relative_to(REPOSITORY)
	return importlib.import_module(".".join(relative.with_suffix("").parts))


navbar.get_module = get_module
generate_pot("ai_munimji")
