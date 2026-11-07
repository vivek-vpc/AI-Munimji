"""The audit seal on DocTypes: append only for everyone, the same chain as on the other backends, and a tampered record is found.

Three things are shown, each by something that can fail:
  * the chain the engine builds over the Frappe stores is, hash for hash, the one SQLite gives (`AUDIT_GOLDEN` in the engine's test-kit, pinned to SQLite and memory in erpnext-ai-agents);
  * no role can change or delete a row by permission, and the controller refuses it for everyone who gets past the permission rows; each barrier is shown alone, with the other taken away;
  * what no controller can stop (a write that is not a document: frappe.db.set_value, frappe.db.delete, SQL) is found by `verify()`.
"""

from unittest import mock

import frappe
from ai_munimji_engine.core.audit import AuditChain
from ai_munimji_engine.stores import memory_core_stores
from ai_munimji_engine.testkit import stores as k
from frappe.tests import IntegrationTestCase

from ai_munimji.ai_munimji.doctype.munimji_audit_seal.munimji_audit_seal import MunimjiAuditSeal
from ai_munimji.stores import frappe_core_stores
from ai_munimji.tests.helpers import empty_store_tables, make_user

SEAL = "Munimji Audit Seal"


def history(core) -> AuditChain:
	"""The engine's known history (two closed requests, an open one, a change of settings), made in these stores; returns the chain over it, nothing sealed yet."""
	return k.audit_history(core)


class SealCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user("Administrator")
		self.savepoint = f"seal_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(self.savepoint)
		empty_store_tables()
		self.core = frappe_core_stores(system=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.savepoint)

	def sealed(self) -> AuditChain:
		chain = history(self.core)
		self.assertEqual(chain.sweep(), 4, "a1, a2 and the two changes of settings are sealed; a3 is open")
		return chain


class TestTheSameChainAsTheOtherBackends(SealCase):
	def test_the_chain_is_the_golden_one_hash_for_hash(self):
		# AUDIT_GOLDEN is the seal over this history as SQLite gives it (erpnext-ai-agents, tests/test_audit_golden.py pins SQLite and memory to it)
		chain = self.sealed()
		verdict = chain.verify()
		self.assertTrue(verdict["ok"], verdict)
		self.assertEqual((verdict["entries"], verdict["not_sealed_yet"]), (4, 0))
		self.assertEqual(verdict["latest_hash"], k.AUDIT_GOLDEN["latest_hash"])
		entries = self.core.audit.entries()
		self.assertEqual([e["hash"] for e in entries], k.AUDIT_GOLDEN["hashes"])
		self.assertEqual([(e["source"], e["ref_id"], e["event"]) for e in entries], k.AUDIT_GOLDEN["events"])

	def test_it_is_also_the_chain_over_the_in_memory_stores(self):
		self.sealed()
		memory = history(memory_core_stores())
		memory.sweep()
		self.assertEqual(self.core.audit.entries(), memory.store.entries())
		self.assertEqual(self.core.audit.entries(), memory.store.entries())

	def test_a_sweep_seals_only_what_is_new(self):
		chain = self.sealed()
		self.assertEqual(chain.sweep(), 0)
		self.core.approvals.decide_if_pending("a3", '{"action":"reject"}', k.T3)
		self.assertEqual(chain.sweep(), 1)
		self.assertEqual([e["seq"] for e in self.core.audit.entries()], [1, 2, 3, 4, 5])
		self.assertTrue(chain.verify()["ok"])

	def test_appending_is_the_scheduled_jobs_work_not_a_person_s(self):
		person = frappe_core_stores(system=False)
		with self.assertRaises(frappe.PermissionError):
			person.audit.append(k.T0, "approval", "a1", "decided", "d", "p", "h")


class TestNoOneCanChangeOrDeleteARow(SealCase):
	def row(self):
		self.sealed()
		return frappe.get_doc(SEAL, self.core.audit.entries()[1]["seq"])

	def manager(self, role: str = "System Manager") -> str:
		return make_user(f"seal.{role.split()[-1].lower()}@example.com", (role,))

	def test_administrator_cannot_change_a_row(self):
		doc = self.row()
		doc.digest = "0" * 64
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		again = frappe.get_doc(SEAL, doc.name)
		again.digest = "0" * 64
		with self.assertRaises(frappe.PermissionError):
			again.save(ignore_permissions=True)

	def test_nobody_can_delete_a_row_not_even_by_force(self):
		doc = self.row()
		with self.assertRaises(frappe.PermissionError):
			doc.delete()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(SEAL, doc.name, force=True, ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.rename_doc(SEAL, doc.name, "99", force=True)
		self.assertEqual(len(self.core.audit.entries()), 4)

	def test_system_manager_cannot_change_or_delete_by_permission_alone(self):
		# the controller's guard is taken away: what is left is what the permission rows say
		doc = self.row()
		person = self.manager("System Manager")
		with (
			mock.patch.object(MunimjiAuditSeal, "refuse_to_change", lambda self: None),
			mock.patch.object(MunimjiAuditSeal, "on_trash", lambda self: None),
		):
			frappe.set_user(person)
			own = frappe.get_doc(SEAL, doc.name)
			own.digest = "0" * 64
			with self.assertRaises(frappe.PermissionError):
				own.save()
			with self.assertRaises(frappe.PermissionError):
				frappe.delete_doc(SEAL, doc.name)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{
						"doctype": SEAL,
						"at": k.T0,
						"source": "approval",
						"ref_id": "x",
						"event": "e",
						"digest": "d",
						"prev": "p",
						"hash": "h",
					}
				).insert()

	def test_a_manager_may_read_the_seal_and_an_approver_may_not(self):
		doc = self.row()
		frappe.set_user(self.manager("Munimji Manager"))
		self.assertEqual(frappe.get_doc(SEAL, doc.name).source, "approval")
		self.assertEqual(len(frappe.get_list(SEAL)), 4)
		frappe.set_user(make_user("seal.approver@example.com", ("Munimji Approver",)))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(SEAL)

	def test_the_guard_is_what_stops_administrator_and_without_it_the_chain_says_so(self):
		# the negative control for the guard: with it taken away Administrator changes a row through the document, and the only thing left that notices is verify()
		chain = self.sealed()
		doc = frappe.get_doc(SEAL, self.core.audit.entries()[1]["seq"])
		with mock.patch.object(MunimjiAuditSeal, "refuse_to_change", lambda self: None):
			doc.digest = "0" * 64
			doc.save()
		verdict = chain.verify()
		self.assertFalse(verdict["ok"])
		self.assertTrue(
			any("seal itself was edited" in p or "was changed" in p for p in verdict["problems"]), verdict
		)

	def test_a_fork_of_the_chain_is_refused_by_the_database(self):
		self.sealed()
		last = self.core.audit.entries()[-1]
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": SEAL,
					"seq": 99,
					"at": k.T3,
					"source": "approval",
					"ref_id": "forged",
					"event": "e",
					"digest": "d",
					"prev": self.core.audit.entries()[-2]["hash"],
					"hash": "h",
				}
			).insert()
		self.assertEqual(self.core.audit.last_hash(), last["hash"])


class TestATamperedRecordIsFound(SealCase):
	def test_a_changed_answer_is_found(self):
		chain = self.sealed()
		frappe.db.set_value(
			"Munimji Approval Request",
			"a1",
			"decision_json",
			'{"action":"reject","actor_id":"priya","channel":"desk"}',
		)
		verdict = chain.verify()
		self.assertFalse(verdict["ok"])
		self.assertEqual(len(verdict["problems"]), 1)
		self.assertIn("request a1 was changed after it was sealed", verdict["problems"][0])

	def test_a_changed_request_a_changed_date_and_a_changed_note_are_found(self):
		for column, value in (
			("request_json", '{"title":"another"}'),
			("created_at", "2026-10-15 08:00:00"),
			("status_note", "edited later"),
		):
			with self.subTest(column=column):
				frappe.db.savepoint("tamper")
				chain = self.sealed()
				frappe.db.set_value("Munimji Approval Request", "a1", column, value)
				self.assertIn("a1", " ".join(chain.verify()["problems"]))
				frappe.db.rollback(save_point="tamper")
				empty_store_tables()

	def test_a_deleted_request_is_found(self):
		chain = self.sealed()
		frappe.db.delete("Munimji Approval Request", {"name": "a2"})
		verdict = chain.verify()
		self.assertFalse(verdict["ok"])
		self.assertIn("request a2 was deleted after it was sealed", " ".join(verdict["problems"]))

	def test_a_changed_setting_record_is_found(self):
		chain = self.sealed()
		frappe.db.set_value("Munimji Settings Change", "1", "new_json", "99")
		self.assertIn(
			"settings change 1 was changed after it was sealed", " ".join(chain.verify()["problems"])
		)

	def test_an_edited_seal_row_and_a_removed_seal_row_are_found(self):
		chain = self.sealed()
		frappe.db.set_value(SEAL, "2", "digest", "0" * 64)
		self.assertIn("the seal itself was edited", " ".join(chain.verify()["problems"]))
		frappe.db.rollback(save_point=self.savepoint)
		empty_store_tables()
		chain = self.sealed()
		frappe.db.delete(SEAL, {"name": "2"})
		verdict = chain.verify()
		self.assertFalse(verdict["ok"], "an entry taken out of the middle breaks the chain at the next one")
		self.assertEqual(verdict["entries"], 3)

	def test_an_untouched_history_is_not_accused(self):
		self.assertEqual(self.sealed().verify()["problems"], [])
