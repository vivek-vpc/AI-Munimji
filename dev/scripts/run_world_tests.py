# Runs the tests that need the contract world (ai_munimji/tests/world) on the site this script runs on: the Frappe client against real data, as real users.
# The world must be loaded first (load_contract_world.py). Give module names to run only those (ai_munimji.tests.world.test_taxes); with none, all of them are run.
# It fails if the world is not there: a run in which the world tests skipped themselves is not a pass. The repository is $MUNIMJI_REPO (default /workspace/ai_munimji, the dev container).
#   .\dev\world-tests.ps1 [module ...]
import os
import sys
import unittest
from pathlib import Path

root = Path(os.environ.get("MUNIMJI_REPO", "/workspace/ai_munimji"))
if str(root) not in sys.path:
	sys.path.insert(0, str(root))

loader = unittest.defaultTestLoader
suite = loader.loadTestsFromNames(list(args)) if args else loader.discover(str(root / "ai_munimji" / "tests" / "world"), pattern="test_*.py", top_level_dir=str(root))
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
no_world = [str(test) for test, why in result.skipped if "contract world" in why]
print(f"\n{result.testsRun} run, {len(result.failures)} failed, {len(result.errors)} errors, {len(result.skipped)} skipped" + (f" ({len(no_world)} because the contract world is not loaded on this site)" if no_world else ""))
frappe.db.rollback()
sys.exit(0 if result.wasSuccessful() and not no_world else 1)
