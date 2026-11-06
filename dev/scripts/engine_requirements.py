"""Prints name==version for the engine's runtime dependencies as installed in this environment, and everything they need in turn (one per line).
pip-audit reads this list: the app's own dependency line names the engine, which is not on PyPI, so auditing the project folder fails; auditing the installed set does not.
    env/bin/python dev/scripts/engine_requirements.py
"""

import importlib.metadata as metadata
import re
import sys


def name_of(requirement: str) -> str:
	return re.split(r"[ ;<>=!~\[(]", requirement.strip(), maxsplit=1)[0]


def closure(start: str) -> dict[str, str]:
	found: dict[str, str] = {}
	pending = [start]
	while pending:
		name = pending.pop()
		key = name.lower().replace("_", "-")
		if key in found:
			continue
		try:
			dist = metadata.distribution(name)
		except metadata.PackageNotFoundError:
			continue  # an optional or platform-only requirement that is not installed
		found[key] = dist.version
		for requirement in dist.requires or []:
			if "extra ==" in requirement:
				continue  # an extra that nobody asked for
			pending.append(name_of(requirement))
	return found


if __name__ == "__main__":
	deps = closure("ai-munimji-engine")
	if "ai-munimji-engine" not in deps:
		sys.exit("ai-munimji-engine is not installed in this environment: run dev/install-engine.sh first")
	deps.pop("ai-munimji-engine")  # not on PyPI; it is the thing under test, not a dependency to audit
	for name, version in sorted(deps.items()):
		print(f"{name}=={version}")
