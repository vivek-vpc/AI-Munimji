"""The runtime half of the proof that version 0.1 sends nothing out of the site (docs/PRIVACY.md; the static half is tests/test_nothing_leaves.py).

The scheduled job and the whole approval flow run with the outside world cut off: a connection to any address that is not on the site's own private network fails loudly, so do the HTTP
libraries and every way Frappe has of making a request, and so does Frappe's mail. The site's own database and cache (private addresses, or a unix socket) stay reachable. The flow must
still pass, and nothing must have been attempted.
"""

import ipaddress
import socket
from contextlib import contextmanager
from unittest import mock

import frappe
import requests
from ai_munimji_engine.packs.stock_procurement.inventory.messages import KIND as KIND_REORDER
from ai_munimji_engine.packs.stock_procurement.procurement.messages import KIND_PO

from ai_munimji import api, jobs, schedule
from ai_munimji.tests.world import as_administrator, as_user
from ai_munimji.tests.world.test_end_to_end import REQUEST, SETTINGS, EndToEnd


def _private(host) -> bool:
	"""Is this address on the site's own network (loopback, private ranges, link-local)? A name is resolved first."""
	try:
		addresses = [ipaddress.ip_address(host)]
	except ValueError:
		addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
	return all(a.is_private or a.is_loopback or a.is_link_local for a in addresses)


@contextmanager
def cut_off():
	"""Everything that could carry something out of the site fails loudly and is written down in `seen`; the site's own connections go through."""
	seen: dict[str, list] = {"sockets": [], "http": [], "mail": []}
	real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

	def outside(address) -> bool:
		return isinstance(address, tuple) and not _private(address[0])  # a unix socket path is the site's own

	def connect(sock, address, *args, **kwargs):
		if outside(address):
			seen["sockets"].append(address)
			raise AssertionError(f"a connection to {address} was attempted: nothing may leave the site")
		return real_connect(sock, address, *args, **kwargs)

	def connect_ex(sock, address, *args, **kwargs):
		if outside(address):
			seen["sockets"].append(address)
			raise AssertionError(f"a connection to {address} was attempted: nothing may leave the site")
		return real_connect_ex(sock, address, *args, **kwargs)

	def refuse_http(*args, **kwargs):
		seen["http"].append(str(kwargs.get("url") or args[1:2] or args)[:80])
		raise AssertionError("an HTTP request was attempted: nothing may leave the site")

	def mail(*args, **kwargs):
		seen["mail"].append(kwargs.get("subject") or args[:1])
		raise AssertionError("an e-mail was attempted: nothing may leave the site")

	import http.client as http_client
	import urllib.request as url_request

	patches = [
		mock.patch.object(socket.socket, "connect", connect),
		mock.patch.object(socket.socket, "connect_ex", connect_ex),
		mock.patch.object(requests.sessions.Session, "request", refuse_http),
		mock.patch.object(url_request, "urlopen", refuse_http),
		mock.patch.object(http_client.HTTPConnection, "request", refuse_http),
		mock.patch.object(frappe, "sendmail", mail),
	]
	# Frappe's own ways of making a request (frappe.integrations.utils in v16; the older names on frappe itself are patched too if a Frappe still has them)
	from frappe.integrations import utils as integrations

	for module in (integrations, frappe):
		for name in (
			"make_request",
			"make_get_request",
			"make_post_request",
			"make_put_request",
			"make_patch_request",
		):
			if hasattr(module, name):
				patches.append(mock.patch.object(module, name, refuse_http))
	for p in patches:
		p.start()
	try:
		yield seen
	finally:
		for p in reversed(patches):
			p.stop()


class TestTheCutOffBites(EndToEnd):
	"""The control: with the cut-off on, each way out fails loudly. Without this the flow below could pass because nothing was watching."""

	def test_each_way_out_is_stopped_and_written_down(self):
		with cut_off() as seen:
			with self.assertRaises(AssertionError):
				socket.create_connection(("93.184.216.34", 80), timeout=2)  # a public address
			with self.assertRaises(AssertionError):
				requests.get("http://example.com/")
			with self.assertRaises(AssertionError):
				from frappe.integrations.utils import make_post_request

				make_post_request("http://example.com/", data={})
			with self.assertRaises(AssertionError):
				frappe.sendmail(recipients=["someone@example.com"], subject="x", message="y")
		self.assertTrue(seen["sockets"] and seen["http"] and seen["mail"], seen)

	def test_the_sites_own_database_stays_reachable(self):
		with cut_off() as seen:
			self.assertTrue(frappe.db.sql("select 1"))
			frappe.cache.set_value("ai_munimji_cut_off_probe", "reachable")
			self.assertEqual(
				frappe.cache.get_value("ai_munimji_cut_off_probe"), "reachable", "and so is the cache"
			)
		self.assertEqual(seen, {"sockets": [], "http": [], "mail": []})


class TestNothingLeavesTheSite(EndToEnd):
	def test_the_job_and_the_whole_approval_flow_pass_with_the_outside_world_cut_off(self):
		mails_before = frappe.db.count("Email Queue")
		patch = mock.patch.object(
			frappe, "in_test", True
		)  # the notification logs are written at once (see TestTheScheduledJob)
		patch.start()
		self.addCleanup(patch.stop)

		def job_tick():
			with as_administrator():
				frappe.get_doc("Scheduled Job Type", {"method": schedule.METHOD}).execute()
			frappe.db.commit()

		with cut_off() as seen:

			def nothing_attempted(step: str):
				# Frappe's job runner logs an exception of the job and carries on, so the attempt is read from what the cut-off wrote down, at once, not from what fails later
				self.assertEqual(
					seen,
					{"sockets": [], "http": [], "mail": []},
					f"{step} tried to send something out of the site",
				)

			job_tick()  # the job looks at every item of the world; the flow follows this one
			nothing_attempted("the scheduled job")
			[reorder] = [
				r
				for r in self.pending(KIND_REORDER)
				if frappe.db.get_value(REQUEST, r["id"], "item_code") == self.item
			]
			with as_user("approver"):
				started = api.answer(reorder["id"], "approve")
			frappe.db.commit()
			nothing_attempted("approving the reorder")
			job_tick()
			nothing_attempted("the scheduled job, the second time")
			[order] = self.pending(KIND_PO)
			with as_user("approver"):
				ordered = api.answer(order["id"], "approve")
				again = api.answer(order["id"], "approve")
			frappe.db.commit()
			nothing_attempted("approving the order")

		self.assertEqual(seen, {"sockets": [], "http": [], "mail": []}, "nothing was attempted")
		self.assertTrue(started["ok"] and ordered["ok"], (started, ordered))
		self.assertFalse(again["ok"], "and the second press is refused, as always")
		[proposal] = self.proposals()
		self.assertTrue(proposal["po_name"], "the draft order was made")
		self.remember("Purchase Order", proposal["po_name"])
		self.assertEqual(frappe.db.count("Email Queue"), mails_before, "no e-mail was queued either")
		self.assertGreaterEqual(
			frappe.db.count("Notification Log", {"document_type": REQUEST}),
			2,
			"the flow did make its notifications, in the Desk bell, so the path that could have sent mail was walked",
		)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "enabled"), 1)
