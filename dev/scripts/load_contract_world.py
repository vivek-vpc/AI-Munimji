# Loads the world of the shared ERP-client checks (ai_munimji_engine.testkit.world) into the site this script runs on, in process, and writes dev/contract-site.json: the reference day
# and the names the site gave its parts. Safe to run again: it finds what exists by its marker and posts the rest. It needs the company that .\dev\scripts\seed.py makes.
# The repository is $MUNIMJI_REPO (default /workspace/ai_munimji, the dev container).
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/load_contract_world.py
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("MUNIMJI_REPO", "/workspace/ai_munimji"))
sys.path.insert(0, str(REPO / "dev" / "scripts"))
from ai_munimji_engine.testkit.loader import run
from inprocess_writer import InProcessWriter

OUT = REPO / "dev" / "contract-site.json"
writer = InProcessWriter()
site = run(writer, OUT)
print("Summary:\n" + writer.summary())
print(f"Company {site['company']} ({site['abbr']}); reference day {site['today']}; described in {OUT}")
