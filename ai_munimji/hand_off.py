"""What happens to a reorder a person has approved: the vendors are compared within about a minute, not at the next scheduled check (Group 2, F1 of the production-readiness review).

Approving a reorder request makes a work order (the engine's hand-off from the inventory step to the procurement step). Until now the procurement step ran only inside the scheduled stock
check, so a request approved at 10 in the morning had its vendors compared the next day at 6. `HandOff` is told of every work order a person's answer makes (the engine's own
`WorkOrderQueue.subscribe`) and queues `jobs.run_vendor_comparison` for it with `enqueue_after_commit`: the job starts only when the answer is in the database, and never for an answer that
was rolled back. The job reads the tax figures as Administrator, which the person's own session cannot, so it is not run in their session (`jobs.run_vendor_comparison`).

If nothing could be queued (Watch stock is off, or the queue could not be reached) the work order stays as it is and the next scheduled check compares the vendors; `outcome` says which, so that
the sentence the person reads (next_step.py) tells the truth.
"""

import frappe
from ai_munimji_engine.core.workorders import REORDER_NEEDED

LOG = "ai_munimji"
JOB = "ai_munimji.jobs.run_vendor_comparison"
QUEUE = "long"
TIMEOUT = 10 * 60  # seconds: one item's vendors and taxes take seconds; this only stops a job that is stuck

QUEUED, OFF, FAILED = (
	"queued",
	"off",
	"failed",
)  # what became of the hand-off, for the sentence the person reads


def queue_vendor_comparison(work_order_id: str) -> None:
	"""Put the comparison for this one work order on the long queue, to start once the current transaction is committed."""
	frappe.enqueue(JOB, queue=QUEUE, timeout=TIMEOUT, enqueue_after_commit=True, work_order_id=work_order_id)


class HandOff:
	"""A listener for the work orders that one person's answer makes. It never raises: a hand-off that fails must not undo an answer (the scheduled check still compares the vendors)."""

	def __init__(self) -> None:
		self.outcome: str | None = None  # None until a reorder's work order has been made
		self.work_orders: list[str] = []

	def __call__(self, work_order: dict) -> None:
		if work_order.get("type") != REORDER_NEEDED:
			return
		self.work_orders.append(work_order["id"])
		if not frappe.get_cached_doc("AI Munimji Settings").enabled:
			self.outcome = (
				OFF  # the scheduled check does nothing while Watch stock is off, and neither does this
			)
			return
		try:
			queue_vendor_comparison(work_order["id"])
		except Exception:
			frappe.logger(LOG).warning(
				f"the vendor comparison for work order {work_order['id']} could not be queued; the scheduled check will make it",
				exc_info=True,
			)
			self.outcome = FAILED
			return
		self.outcome = QUEUED
