"""The app sends nothing out of the site and calls no model unless a Munimji Manager switches Telegram on (docs/PRIVACY.md says so). This is the static half of the proof: no module of the app
imports a network, mail or model library, and none calls Frappe's mail or outbound-request functions, except the one named below. The runtime half, with sockets, HTTP and mail cut off while the job and the whole approval flow run, is
tests/world/test_nothing_leaves.py.

An exception is a decision: name the module in EXCEPTIONS with the reason. There is one: the transport of Telegram.
"""

import ast
import re
import unittest

from ai_munimji.tests import scan

EXCEPTIONS: dict[str, str] = {
	"ai_munimji/telegram/transport.py": "the one module that talks to Telegram: only while a Munimji Manager has switched Telegram on and given it a bot token, and only to the address in telegram/config.py "
	"(api.telegram.org, or the one a site's own configuration names, which no page can). It imports requests and nothing else that reaches out; docs/PRIVACY.md says what is sent."
}
# The web addresses written in the app's Python, and nothing else: Telegram's, and a link to it that a person is given (never called by the app).
ADDRESSES = {"https://api.telegram.org", "https://t.me/{bot}?start={code}"}

# a module is forbidden if the import names it or something inside it (urllib.request, but not urllib.parse)
NETWORK = {
	"requests",
	"urllib3",
	"httpx",
	"aiohttp",
	"socket",
	"smtplib",
	"ftplib",
	"imaplib",
	"poplib",
	"telnetlib",
	"http.client",
	"urllib.request",
	"xmlrpc.client",
	"websocket",
	"websockets",
	"paramiko",
	"pycurl",
	"grpc",
}
MODEL_SDKS = {
	"openai",
	"anthropic",
	"ollama",
	"litellm",
	"langchain",
	"langchain_core",
	"langchain_openai",
	"cohere",
	"mistralai",
	"groq",
	"google.generativeai",
	"google.genai",
	"vertexai",
	"transformers",
	"huggingface_hub",
	"boto3",
	"replicate",
	"together",
	"llama_cpp",
}
FRAPPE_OUTBOUND_MODULES = {
	"frappe.integrations",
	"frappe.email.queue",
	"frappe.core.doctype.communication.email",
}
FRAPPE_OUTBOUND_CALLS = {"sendmail", "make_post_request", "make_get_request", "make_put_request"}


def _inside(name: str, banned: set[str]) -> bool:
	return any(name == b or name.startswith(b + ".") for b in banned)


def problems_in(source: str, filename: str) -> list[str]:
	found = []
	banned = NETWORK | MODEL_SDKS | FRAPPE_OUTBOUND_MODULES
	for node in ast.walk(ast.parse(source, filename)):
		if isinstance(node, ast.Import):
			for alias in node.names:
				if _inside(alias.name, banned):
					found.append(f"{filename}:{node.lineno}: imports {alias.name}")
		elif isinstance(node, ast.ImportFrom):
			module = node.module or ""
			if _inside(module, banned):
				found.append(f"{filename}:{node.lineno}: imports from {module}")
			for alias in node.names:  # from urllib import request
				if _inside(f"{module}.{alias.name}", banned):
					found.append(f"{filename}:{node.lineno}: imports {module}.{alias.name}")
		elif isinstance(node, ast.Call):
			f = node.func
			if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "frappe":
				if f.attr in FRAPPE_OUTBOUND_CALLS:
					found.append(f"{filename}:{node.lineno}: calls frappe.{f.attr}")
			# a library named only by a string: __import__("requests"), importlib.import_module("requests")
			name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
			if name in ("__import__", "import_module") and node.args:
				arg = node.args[0]
				if (
					isinstance(arg, ast.Constant)
					and isinstance(arg.value, str)
					and _inside(arg.value, banned)
				):
					found.append(f"{filename}:{node.lineno}: imports {arg.value} by name")
		elif isinstance(node, ast.Attribute):
			# frappe.integrations.<anything>, however it was reached
			if node.attr == "integrations" and isinstance(node.value, ast.Name) and node.value.id == "frappe":
				found.append(f"{filename}:{node.lineno}: uses frappe.integrations")
	return found


# the browser side: an address that is not the site's own, or a call that opens a connection by itself
BROWSER = re.compile(r"https?://|XMLHttpRequest|\bfetch\(|sendBeacon|new WebSocket|new EventSource", re.I)


class TestNothingIsImportedOrCalledThatCouldSendAnything(unittest.TestCase):
	def test_no_module_of_the_app_imports_or_calls_anything_that_leaves_the_site(self):
		problems, scanned = [], []
		for path in scan.python_files():
			name = scan.relative(path)
			scanned.append(name)
			if name in EXCEPTIONS:
				continue
			problems += problems_in(path.read_text(encoding="utf-8"), name)
		self.assertEqual(problems, [])
		# the scan sees the app, and the exceptions are real modules with a reason
		self.assertGreaterEqual(len(scanned), 30)
		for needed in (
			"ai_munimji/jobs.py",
			"ai_munimji/api.py",
			"ai_munimji/erp_client.py",
			"ai_munimji/install.py",
		):
			self.assertIn(needed, scanned)
		for module, reason in EXCEPTIONS.items():
			self.assertTrue((scan.ROOT / module).exists() and reason)

	def test_no_script_of_the_app_talks_to_an_address_of_its_own_choosing(self):
		files = scan.javascript_files()
		self.assertTrue(files, "the scan sees the app's scripts")
		found = []
		for path in files:
			for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
				code = line.split("//")[0] if "http" not in line.split("//")[0] else line
				if BROWSER.search(code) and not line.lstrip().startswith(("//", "*")):
					found.append(f"{scan.relative(path)}:{number}: {line.strip()[:90]}")
		self.assertEqual(found, [])

	def test_the_scan_catches_each_kind_of_thing_it_is_for(self):
		for source in (
			"import requests\n",
			"import requests.adapters\n",
			"from requests import get\n",
			"import urllib.request\n",
			"from urllib import request\n",
			"from urllib.request import urlopen\n",
			"import http.client\n",
			"import httpx\n",
			"import socket\n",
			"import smtplib\n",
			"import aiohttp\n",
			"import openai\n",
			"from anthropic import Anthropic\n",
			"import ollama\n",
			"from langchain_openai import ChatOpenAI\n",
			"import frappe\nfrappe.sendmail(recipients=['a@b.c'])\n",
			"import frappe\nfrappe.make_post_request('http://x', data={})\n",
			"import frappe\nfrappe.make_get_request('http://x')\n",
			"import frappe\nfrappe.integrations.utils.make_post_request('http://x')\n",
			"from frappe.integrations.utils import make_post_request\n",
			"__import__('requests')\n",
			"import importlib\nimportlib.import_module('openai')\n",
		):
			self.assertTrue(problems_in(source, "x.py"), f"not caught: {source!r}")
		for source in (
			"from urllib.parse import quote\n",
			"import urllib.parse\n",
			"import frappe\nfrappe.get_doc({}).insert()\n",
			"import json, re\n",
			"import click\n",
		):
			self.assertEqual(problems_in(source, "x.py"), [], f"wrongly caught: {source!r}")

	def test_the_browser_scan_catches_what_it_is_for(self):
		for line in (
			"fetch('https://example.com/x')",
			"const r = new XMLHttpRequest()",
			"navigator.sendBeacon('/x')",
			"const ws = new WebSocket('wss://x')",
		):
			self.assertTrue(BROWSER.search(line), line)
		self.assertFalse(BROWSER.search("frappe.call({method: 'ai_munimji.api.answer'})"))


class TestTelegramIsTheOnlyWayOut(unittest.TestCase):
	"""The exception is as small as it can be: one module, one library, two addresses."""

	def test_only_the_transport_imports_a_network_library_and_only_requests(self):
		importers = {}
		for path in scan.python_files():
			tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
			names = set()
			for node in ast.walk(tree):
				if isinstance(node, ast.Import):
					names |= {a.name for a in node.names}
				elif isinstance(node, ast.ImportFrom) and node.module:
					names.add(node.module)
			network = {n for n in names if _inside(n, NETWORK)}
			if network:
				importers[scan.relative(path)] = network
		self.assertEqual(importers, {"ai_munimji/telegram/transport.py": {"requests"}})

	def test_the_only_web_addresses_written_in_the_apps_python_are_telegrams(self):
		found = set()
		for path in scan.python_files():
			tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
			parts = {
				id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values
			}  # the pieces of an f-string are read with it, not alone
			for node in ast.walk(tree):
				if (
					isinstance(node, ast.Constant)
					and id(node) not in parts
					and isinstance(node.value, str)
					and re.match(r"https?://", node.value)
				):
					found.add(node.value)
				elif isinstance(
					node, ast.JoinedStr
				):  # an f-string: its fixed parts, with {name} where a value goes
					text = "".join(
						p.value if isinstance(p, ast.Constant) else "{" + ast.unparse(p.value) + "}"
						for p in node.values
					)
					if re.match(r"https?://", text):
						found.add(text)
		self.assertEqual(found, ADDRESSES)

	def test_the_transport_is_given_no_address_of_its_own(self):
		source = (scan.ROOT / "ai_munimji/telegram/transport.py").read_text(encoding="utf-8")
		self.assertNotRegex(source, r"https?://")
		self.assertIn("allow_redirects=False", source, "a redirect is refused: the token is in every address")
