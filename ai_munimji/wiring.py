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
from ai_munimji.hand_off import HandOff
from ai_munimji.stores import frappe_core_stores, frappe_stock_stores
from ai_munimji.telegram import outbox

SETTINGS = "AI Munimji Settings"
REQUEST = "Munimji Approval Request"


class SiteApprovalService(ApprovalService):
	"""The engine's approval service, with one difference for a service that has no channel to write to: the stock check, which makes its requests inside transactions that lock rows.
	The engine's agents ask `deliver(record)` for each new request (and the engine's own code asks it for a revised one). A service with channels sends it at once, which is right for a
	person's answer and for the job whose business is sending. One without channels cannot, and does not need to: it asks the outbox (telegram/outbox.py), which queues a job once the work
	is committed, and does nothing at all while Telegram is off."""

	def deliver(self, record) -> None:
		if self.router.channels:
			super().deliver(record)
		else:
			outbox.nudge(record)


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
	hand_off: Any = None  # a person's services only: what became of the vendor comparison for a reorder they approved (hand_off.py)


def build(erp, core, clock=None, settings_doc=None, router=None) -> Services:
	"""The services over `core` (a bundle of DocType stores) and `erp`. `settings_doc` is the settings page as a document, or anything with .get; by default the site's own.

	`router` is who is written to by message. By default nobody is (a person answers in the Desk). With Telegram on, a caller that answers a person or tidies a chat passes
	`telegram_router()`. The stock check does not: it must not send anything while it holds rows locked. It asks for a delivery instead (a new request calls `outbox.nudge`), and a job
	sends it once the work is committed (telegram/outbox.py)."""
	clock = clock or utcnow
	stock = frappe_stock_stores(core)
	values = settings_map.to_engine(settings_doc or frappe.get_cached_doc(SETTINGS))
	values["system"]["timezone"] = (
		get_system_timezone()
	)  # the time zone is Frappe's own, not a second setting (settings_map.py)
	settings = SettingsStore(core.settings, base_system=values["system"], clock=clock)
	attach_settings(settings, base_policy=values["policy"], base_calendar=values["calendar"])
	approvals = SiteApprovalService(
		core.approvals,
		router or ApprovalRouter({}, []),
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


def telegram_router(for_desk: bool = False):
	"""The router with Telegram in it, or None while Telegram is off. `for_desk`: for an answer given in the Desk, whose calls to Telegram (tidying the chat) are kept short."""
	from ai_munimji.telegram import router

	return router.build(for_desk)


def person_services(clock=None, telegram: bool = False, for_desk: bool = True) -> Services:
	"""The services as a signed-in person runs them: ERPNext is read and written as that person, and the records are kept through the permissions of their roles.

	A reorder this person approves makes a work order, and the vendors for it are compared in the background once the answer is committed (hand_off.py), not at the next scheduled check.
	`telegram`: with Telegram on, the people the request was sent to are told what came of it (the buttons go, the outcome appears under it). An answer that came from Telegram itself
	passes `for_desk=False`: nobody is waiting for a page, so its calls to Telegram need not be kept short."""
	router = telegram_router(for_desk) if telegram else None
	services = build(FrappeERPClient(), frappe_core_stores(), clock, router=router)
	services.hand_off = HandOff()
	services.workorders.subscribe(services.hand_off)
	return services
