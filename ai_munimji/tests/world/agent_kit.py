"""The engine's order-preparing agent, on the engine's own in-memory stores, with whatever ERP client a test gives it. The Frappe app keeps its proposals in DocTypes later (Phase 4b);
until then this is how the tests let the real agent, and not a copy of its logic, read the real site through the real client."""

from datetime import datetime, time, timezone

from ai_munimji_engine.core.approvals.router import ApprovalRouter
from ai_munimji_engine.core.approvals.service import ApprovalService
from ai_munimji_engine.core.common import Actor
from ai_munimji_engine.core.settings_store import SettingsStore
from ai_munimji_engine.core.workorders import REORDER_NEEDED, WorkOrderQueue
from ai_munimji_engine.packs.stock_procurement.procurement.agent import ProcurementAgent
from ai_munimji_engine.packs.stock_procurement.procurement.proposals import ProposalRepo
from ai_munimji_engine.packs.stock_procurement.settings import attach as attach_settings
from ai_munimji_engine.stores import memory_core_stores
from ai_munimji_engine.stores.stock import memory_stock_stores

OWNER = Actor(id="owner", roles=frozenset({"admin", "approver"}), via="test")
COST_ONLY = {"weight_cost": 100, "weight_delivery": 0, "weight_reliability": 0, "weight_terms": 0}


class Kit:
	def __init__(self, erp, today, **procurement):
		noon = datetime.combine(today, time(12, 0), tzinfo=timezone.utc)
		self.clock = lambda: noon
		self.core = memory_core_stores()
		self.stock = memory_stock_stores(self.core.backend)
		self.settings = SettingsStore(self.core.settings, clock=self.clock)
		attach_settings(self.settings)
		self.settings.update_procurement(OWNER, {**COST_ONLY, **procurement})
		self.approvals = ApprovalService(self.core.approvals, ApprovalRouter({}, []), system_settings=self.settings.system, clock=self.clock, inbound=self.core.inbound)
		self.workorders = WorkOrderQueue(self.core.workorders, self.clock)
		self.proposals = ProposalRepo(self.stock.proposals, self.clock)
		self.agent = ProcurementAgent(erp, self.settings, self.proposals, self.approvals, self.workorders, self.stock.runs, self.core.transaction, self.clock)

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
