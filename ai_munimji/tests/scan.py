"""Source files of the app, for the tests that read the code itself (test_translations.py, test_rules.py). The tests are not part of what is scanned, and neither are generated files."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]  # .../ai_munimji, the Python package
ROOT = PACKAGE.parent
SKIP_DIRECTORIES = {"__pycache__", "tests", "patches", "node_modules", "dist", "locale"}


def _wanted(path: Path) -> bool:
	relative = path.relative_to(PACKAGE)
	return not (SKIP_DIRECTORIES & set(relative.parts[:-1])) and not relative.name.startswith("test_")


def python_files() -> list[Path]:
	return [p for p in sorted(PACKAGE.rglob("*.py")) if _wanted(p)]


def javascript_files() -> list[Path]:
	return [p for p in sorted(PACKAGE.rglob("*.js")) if _wanted(p)]


def doctype_files() -> list[Path]:
	return [p for p in sorted((PACKAGE / "ai_munimji" / "doctype").glob("*/*.json")) if p.stem == p.parent.name]


def relative(path: Path) -> str:
	return path.relative_to(ROOT).as_posix()
