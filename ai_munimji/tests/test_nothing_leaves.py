"""Version 0.1 sends nothing out of the site and calls no model (docs/PRIVACY.md says so). This is the static half of the proof: no module of the app imports a network, mail or model
library, and none calls Frappe's mail or outbound-request functions. The runtime half, with sockets, HTTP and mail cut off while the job and the whole approval flow run, is
tests/world/test_nothing_leaves.py.

An exception is a decision: name the module in EXCEPTIONS with the reason. There is none.
"""

import ast
import re
import unittest

from ai_munimji.tests import scan

EXCEPTIONS: dict[str, str] = {}

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
