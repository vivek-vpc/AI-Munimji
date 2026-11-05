import tomllib
import unittest
from pathlib import Path

from ai_munimji import hooks

ROOT = Path(__file__).resolve().parents[2]


class TestPublisherContact(unittest.TestCase):
	"""The contact is public (the Marketplace shows it): hooks.py and pyproject.toml must name the same one, and never the template's placeholder."""

	def test_hooks_and_pyproject_name_the_same_contact(self):
		project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
		self.assertEqual({author["email"] for author in project["authors"]}, {hooks.app_email})

	def test_the_contact_is_not_the_placeholder(self):
		self.assertNotIn("example.com", hooks.app_email)
		self.assertIn("@", hooks.app_email)

	def test_the_skeleton_script_gives_the_template_the_same_contact(self):
		script = (ROOT / "dev" / "new-app.sh").read_text(encoding="utf-8")
		self.assertIn(f'"{hooks.app_email}"', script)
		self.assertNotIn("example.com", script)
