"""The engine's services, put together for this site: its stores are the DocTypes, its settings are the AI Munimji Settings page, and nobody is written to by message (a person answers in
the Desk, so the router has no channels and no recipients).

`build(erp, core)` is the one place that knows how the pieces fit; the scheduled job (jobs.py, with the system-mode client and stores) and a person's answer (api.py, with the client and
stores of the signed-in person) both call it. A test calls it with whatever client it wants to look at.
"""

from dataclasses import dataclass
from typing import Any

import frappe
from ai_munimji_engine.core.approvals.router import ApprovalRouter
from ai_munimji_engine.core.approvals.service import ApprovalService
from ai_munimji_engine.core.audit import AuditChain
from ai_munimji_engine.core.common import Actor, utcnow
from ai_munimji_engine.core.settings_store import SettingsStore
from ai_munimji_engine.core.workorders import WorkOrderQueue
from ai_munimji_engine.packs.stock_procurement.inventory.agent import InventoryAgent
from ai_munimji_engine.packs.stock_procurement.inventory.alerts import AlertRepo
from ai_munimji_engine.packs.stock_procurement.procurement.agent import ProcurementAgent
from ai_munimji_engine.packs.stock_procurement.procurement.proposals import ProposalRepo
from ai_munimji_engine.packs.stock_procurement.settings import attach as attach_settings
from frappe.utils import get_system_timezone

from ai_munimji import settings_map
from ai_munimji.erp_client import FrappeERPClient
from ai_munimji.stores import frappe_core_stores, frappe_stock_stores

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"


@dataclass
class Services:
	core: Any
	stock: Any
	erp: Any
	settings: SettingsStore
	approvals: ApprovalService
	workorders: WorkOrderQueue
	proposals: ProposalRepo
	alerts: AlertRepo
	inventory: InventoryAgent
	procurement: ProcurementAgent
	audit: AuditChain
	clock: Any


def build(erp, core, clock=None, settings_doc=None) -> Services:
	"""The services over `core` (a bundle of DocType stores) and `erp`. `settings_doc` is the settings page as a document, or anything with .get; by default the site's own."""
	clock = clock or utcnow
	stock = frappe_stock_stores(core)
	values = settings_map.to_engine(settings_doc or frappe.get_cached_doc(SETTINGS))
	values["system"]["timezone"] = (
		get_system_timezone()
	)  # the time zone is Frappe's own, not a second setting (settings_map.py)
	settings = SettingsStore(core.settings, base_system=values["system"], clock=clock)
	attach_settings(settings, base_policy=values["policy"], base_calendar=values["calendar"])
	approvals = ApprovalService(
		core.approvals,
		ApprovalRouter({}, []),
		system_settings=settings.system,
		clock=clock,
		inbound=core.inbound,
	)
	workorders = WorkOrderQueue(core.workorders, clock)
	proposals = ProposalRepo(stock.proposals, clock)
	alerts = AlertRepo(stock.alerts, clock)
	inventory = InventoryAgent(erp, settings, alerts, approvals, workorders, stock, core.transaction, clock)
	procurement = ProcurementAgent(
		erp, settings, proposals, approvals, workorders, stock.runs, core.transaction, clock
	)
	return Services(
		core=core,
		stock=stock,
		erp=erp,
		settings=settings,
		approvals=approvals,
		workorders=workorders,
		proposals=proposals,
		alerts=alerts,
		inventory=inventory,
		procurement=procurement,
		audit=AuditChain(core.audit, clock),
		clock=clock,
	)


def actor_for(user: str | None = None, via: str = "desk") -> Actor:
	"""The engine's idea of the signed-in person: what Frappe lets them do, as the three capabilities the engine knows. 'look' is the right to read the app's requests, 'decide' the
	right to approve one (the DocType's `approve` right, which also asks for the right to create a Purchase Order: permissions.py), 'settings' the right to change the settings page."""
	user = user or frappe.session.user
	caps = set()
	if frappe.has_permission(REQUEST, "read", user=user):
		caps.add("look")
	if frappe.has_permission(REQUEST, "approve", user=user):
		caps.add("decide")
	if frappe.has_permission(SETTINGS, "write", user=user):
		caps.add("settings")
	return Actor(id=user, roles=frozenset(), via=via, caps=frozenset(caps))


def person_services(clock=None) -> Services:
	"""The services as a signed-in person runs them: ERPNext is read and written as that person, and the records are kept through the permissions of their roles."""
	return build(FrappeERPClient(), frappe_core_stores(), clock)
