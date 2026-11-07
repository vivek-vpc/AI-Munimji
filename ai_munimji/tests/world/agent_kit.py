"""The engine's order-preparing agent on this site's DocType stores, with whatever ERP client a test gives it: the real agent, and not a copy of its logic, reads the real site through the real
client and keeps its requests, proposals and work orders in the app's own records. (Until Phase 4b this kit used the engine's in-memory stores.)

The tables of the stores are emptied when a kit is made, inside the test's transaction, and the world tests end with a rollback: a site that holds records is not touched, and one test's
requests are not another test's.
"""

from datetime import UTC, datetime, time

import frappe
from ai_munimji_engine.core.common import Actor
from ai_munimji_engine.core.workorders import REORDER_NEEDED

from ai_munimji import wiring
from ai_munimji.stores import frappe_core_stores
from ai_munimji.tests.helpers import empty_store_tables

OWNER = Actor(id="owner", roles=frozenset({"admin", "approver"}), via="test")
COST_ONLY = {"weight_cost": 100, "weight_delivery": 0, "weight_reliability": 0, "weight_terms": 0}


class Kit:
	def __init__(self, erp, today, **procurement):
		noon = datetime.combine(today, time(12, 0), tzinfo=UTC)
		self.clock = lambda: noon
		empty_store_tables()
		self.services = wiring.build(erp, frappe_core_stores(), self.clock)
		s = self.services
		self.core, self.stock, self.settings = s.core, s.stock, s.settings
		who = frappe.session.user
		frappe.set_user(
			"Administrator"
		)  # the weights are the site owner's setting (a Manager's), whoever then asks for a request
		try:
			self.settings.update_procurement(OWNER, {**COST_ONLY, **procurement})
		finally:
			frappe.set_user(who)
		self.approvals, self.workorders, self.proposals, self.agent = (
			s.approvals,
			s.workorders,
			s.proposals,
			s.procurement,
		)

	def propose(self, item_code: str, qty: float, uom: str = "Nos"):
		"""One reorder for the item, as the stock monitor would raise it; returns the request waiting for an answer."""
		payload = {"item_code": item_code, "item_name": item_code, "item_group": "All Item Groups", "uom": uom, "suggested_qty": qty, "cover_days": 20.0, "lead_time_days": 5.0,
		           "daily_rate": 4.0, "on_hand": 10.0, "severity": "HIGH", "reasons": ["Low."]}  # fmt: skip
		self.workorders.emit(REORDER_NEEDED, payload)
		report = self.agent.run()
		if report.errors:
			raise AssertionError(f"the agent reported errors: {report.errors}")
		return self.approvals.list(status="pending")[0]

	def ranking(self) -> dict:
		return self.proposals.list()[0].ranking

	def change_qty(self, record, qty: float):
		return self.approvals.decide(record.id, "change_qty", OWNER, "desk", {"qty": qty})

	def vendor(self, supplier: str) -> dict:
		return next(v for v in self.ranking()["vendors"] if v["supplier"] == supplier)
