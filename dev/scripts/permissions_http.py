"""Who sees and answers what of the app's records, asked over HTTP of the running bench, as real signed-in people (Phase 4b, step 4).

The bench must be running on http://localhost:8000. The script makes five people and a few records (committed, so that the server sees them), signs each person in, asks the list view
(`frappe.desk.reportview.get`), the form (`frappe.desk.form.load.getdoc`) and the REST API (`/api/resource`) for them, tries to change and to delete them, tries to read a row by
guessing its name, and removes everything it made. It prints one line per check and fails if any differs from what the roles say.
    .\\dev\\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/permissions_http.py
Development tooling: it runs as Administrator on the development site and is not part of the app.
"""

import json
import sys
import urllib.parse

import requests

from ai_munimji.stores import frappe_core_stores, frappe_stock_stores

BASE = "http://localhost:8000"
PASSWORD = "Munimji-dev-1!"
PEOPLE = {
	"viewer": ("perm.viewer@example.com", ("Munimji Viewer",)),
	"approver": ("perm.approver@example.com", ("Munimji Approver",)),
	"manager": ("perm.manager@example.com", ("Munimji Manager",)),
	"stock": (
		"perm.stock@example.com",
		("Stock User", "Purchase User"),
	),  # ERPNext's roles, none of the app's
	"nobody": ("perm.nobody@example.com", ()),
}
REQUEST, ALERT, PROPOSAL, SEAL, OVERRIDE, SETTINGS = (
	"Munimji Approval Request",
	"Munimji Stock Alert",
	"Munimji Purchase Proposal",
	"Munimji Audit Seal",
	"Munimji Settings Override",
	"AI Munimji Settings",
)
T0, T1, T2 = "2026-10-16T08:00:00+00:00", "2026-10-16T09:00:00+00:00", "2026-10-16T10:00:00+00:00"
failed = []


def say(ok: bool, what: str) -> None:
	print(("  PASS  " if ok else "  FAIL  ") + what)
	if not ok:
		failed.append(what)


def make_people() -> None:
	for email, roles in PEOPLE.values():
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		)
		user.flags.ignore_password_policy = True
		user.new_password = PASSWORD
		user.insert(ignore_permissions=True)


def forget_people() -> None:
	for email, _roles in PEOPLE.values():
		frappe.db.delete("User Permission", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)


class Person:
	def __init__(self, key: str) -> None:
		self.key, self.email = key, PEOPLE[key][0]
		self.http = requests.Session()
		login = self.http.post(f"{BASE}/api/method/login", data={"usr": self.email, "pwd": PASSWORD})
		assert login.status_code == 200, (self.email, login.status_code, login.text[:200])
		page = self.http.get(f"{BASE}/app")
		marker = 'csrf_token = "'
		self.csrf = page.text.split(marker, 1)[1].split('"', 1)[0] if marker in page.text else ""

	def get(self, path: str, **params) -> requests.Response:
		return self.http.get(f"{BASE}{path}", params=params)

	def send(self, method: str, path: str, **body) -> requests.Response:
		return self.http.request(
			method, f"{BASE}{path}", json=body or None, headers={"X-Frappe-CSRF-Token": self.csrf}
		)

	def listing(self, doctype: str) -> requests.Response:
		return self.get(
			"/api/method/frappe.desk.reportview.get",
			doctype=doctype,
			fields=json.dumps(["name"]),
			limit_page_length=50,
			start=0,
		)

	def form(self, doctype: str, name: str) -> requests.Response:
		return self.get("/api/method/frappe.desk.form.load.getdoc", doctype=doctype, name=name)

	def resource(self, doctype: str, name: str = "") -> requests.Response:
		return self.get(
			"/api/resource/"
			+ urllib.parse.quote(doctype)
			+ (("/" + urllib.parse.quote(name)) if name else "")
		)


def names_in(response: requests.Response) -> set[str]:
	try:
		data = response.json()
	except ValueError:
		return set()
	message = data.get("message")
	if (
		isinstance(message, dict) and "values" in message
	):  # reportview.get answers {keys: [...], values: [[...]]}
		return {row[0] for row in message["values"]}
	if isinstance(data.get("data"), list):
		return {row["name"] for row in data["data"]}
	return set()


def seed():
	core = frappe_core_stores(system=True)
	stock = frappe_stock_stores(core)
	warehouses = frappe.get_all("Warehouse", filters={"is_group": 0}, pluck="name", limit=2, order_by="name")
	assert len(warehouses) == 2, "the dev site needs two warehouses"
	for name in ("perm-r1", "perm-r2"):
		frappe.db.delete("Munimji Approval Request", {"name": name})
	core.approvals.insert(
		"perm-r1",
		"procurement.po",
		json.dumps(
			{"title": "Reorder bolts", "facts": {"item_code": "BOLT", "warehouse": warehouses[0], "qty": 10}}
		),
		"item",
		"BOLT",
		T0,
		None,
	)
	core.approvals.insert(
		"perm-r2",
		"procurement.po",
		json.dumps(
			{"title": "Reorder nuts", "facts": {"item_code": "NUT", "warehouse": warehouses[1], "qty": 5}}
		),
		"item",
		"NUT",
		T1,
		None,
	)
	core.approvals.decide_if_pending(
		"perm-r2", json.dumps({"action": "approve", "actor_id": "perm.approver@example.com"}), T2
	)
	core.settings.save(
		"item", "BOLT", '{"min_qty": 5}', "perm.manager@example.com", T1, [("min_qty", "null", "5")]
	)
	stock.alerts.insert("perm-a1", "BOLT", "BREACH", 2, T0, "{}", "Low on bolts.", None)
	stock.proposals.insert("perm-p1", "w1", "BOLT", "awaiting", "S1", "Acme", 10.0, 2.5, 25.0, "{}", "", T0)
	from ai_munimji_engine.core.audit import AuditChain

	AuditChain(core.audit).sweep()  # perm-r2 is closed, so it and the settings change are sealed
	frappe.db.commit()
	return warehouses


def cleanup():
	for doctype, names in (
		(REQUEST, ["perm-r1", "perm-r2"]),
		(ALERT, ["perm-a1"]),
		(PROPOSAL, ["perm-p1"]),
	):
		for name in names:
			frappe.db.delete(doctype, {"name": name})
	frappe.db.delete(OVERRIDE, {"scope_key": "BOLT"})
	frappe.db.delete("Munimji Settings Change", {"actor": PEOPLE["manager"][0]})
	frappe.db.delete(SEAL, {"ref_id": ["in", ["perm-r2"]]})
	frappe.db.commit()


make_people()
frappe.db.commit()
warehouses = seed()
try:
	who = {key: Person(key) for key in PEOPLE}
	readers, everyone = {"viewer", "approver", "manager"}, set(PEOPLE)

	print("1. The list view, the form and the REST API of an approval request")
	for key, p in who.items():
		got = p.listing(REQUEST)
		expected = {"perm-r1", "perm-r2"} if key in readers else set()
		say(
			(got.status_code == 200 and expected <= names_in(got))
			if key in readers
			else got.status_code == 403,
			f"{key}: list view answers {got.status_code}"
			+ (
				f", {len(names_in(got) & {'perm-r1', 'perm-r2'})} of the two requests"
				if key in readers
				else ""
			),
		)
		form = p.form(REQUEST, "perm-r1")
		say(
			form.status_code == (200 if key in readers else 403),
			f"{key}: the form of a request answers {form.status_code}",
		)
		api = p.resource(REQUEST, "perm-r1")
		say(
			api.status_code == (200 if key in readers else 403),
			f"{key}: GET /api/resource/{REQUEST}/perm-r1 answers {api.status_code}",
		)
		if key in readers:
			shown = api.json()["data"]
			say(
				json.loads(shown["request_json"])["title"] == "Reorder bolts"
				and shown["status"] == "pending",
				f"{key}: the form shows the engine's request and its status",
			)

	print("2. Guessing a name")
	nobody = who["nobody"]
	for doctype, name in (
		(REQUEST, "perm-r1"),
		(ALERT, "perm-a1"),
		(PROPOSAL, "perm-p1"),
		(SEAL, "1"),
		(OVERRIDE, "anything"),
	):
		r = nobody.resource(doctype, name)
		say(
			r.status_code == 403 and "data" not in r.text[:20],
			f"nobody asks for {doctype} {name}: {r.status_code} and no data",
		)
	r = who["viewer"].resource(SEAL, "1")
	say(r.status_code == 403, f"a viewer asks for the audit seal row 1: {r.status_code}")
	r = who["approver"].listing(SEAL)
	say(r.status_code == 403, f"an approver lists the audit seal: {r.status_code}")
	r = who["stock"].resource(REQUEST, "perm-r1")
	say(
		r.status_code == 403,
		f"a person with ERPNext's roles but none of the app's asks for a request: {r.status_code}",
	)

	print(
		"3. Changing, creating and deleting (the roles may; the app's records are still kept by its stores only)"
	)
	for key, p in who.items():
		put = p.send(
			"PUT",
			"/api/resource/" + urllib.parse.quote(REQUEST) + "/perm-r1",
			status="decided",
			decision_json="{}",
		)
		say(
			put.status_code in (403, 417),
			f"{key}: PUT status=decided on a request is refused ({put.status_code})",
		)
		post = p.send(
			"POST",
			"/api/resource/" + urllib.parse.quote(REQUEST),
			doctype=REQUEST,
			name="perm-new",
			kind="k",
			status="pending",
			request_json="{}",
		)
		say(
			post.status_code in (403, 417),
			f"{key}: creating a request by hand is refused ({post.status_code})",
		)
		gone = p.send("DELETE", "/api/resource/" + urllib.parse.quote(REQUEST) + "/perm-r1")
		say(gone.status_code in (403, 417), f"{key}: deleting a request is refused ({gone.status_code})")
		sv = p.send(
			"POST",
			"/api/method/frappe.client.set_value",
			doctype=REQUEST,
			name="perm-r1",
			fieldname="status",
			value="decided",
		)
		say(
			sv.status_code in (403, 417),
			f"{key}: frappe.client.set_value on a request is refused ({sv.status_code})",
		)
	say(
		frappe.db.get_value(REQUEST, "perm-r1", "status") == "pending",
		"after all that the request is still pending, untouched",
	)
	seal_row = who["manager"].send("PUT", "/api/resource/" + urllib.parse.quote(SEAL) + "/1", digest="0")
	say(
		seal_row.status_code in (403, 417),
		f"even a manager cannot change a seal row ({seal_row.status_code})",
	)
	seal_gone = who["manager"].send("DELETE", "/api/resource/" + urllib.parse.quote(SEAL) + "/1")
	say(seal_gone.status_code in (403, 417), f"or delete one ({seal_gone.status_code})")

	print("4. The other records")
	for doctype, name in ((ALERT, "perm-a1"), (PROPOSAL, "perm-p1")):
		for key in everyone:
			got = who[key].form(doctype, name)
			say(
				got.status_code == (200 if key in readers else 403),
				f"{key}: the form of {doctype} answers {got.status_code}",
			)
	for key in everyone:
		got = who[key].resource(SETTINGS, SETTINGS)  # a Single DocType is addressed by its own name
		say(
			got.status_code == (200 if key == "manager" else 403),
			f"{key}: the settings page answers {got.status_code}",
		)
	say(
		who["manager"].listing("Munimji Settings Change").status_code == 200
		and who["viewer"].listing("Munimji Settings Change").status_code == 403,
		"the change record of the settings is read by the manager and not by a viewer",
	)
	say(who["manager"].listing(SEAL).status_code == 200, "the manager reads the audit seal")

	print(
		"5. A person limited to one warehouse (a User Permission on Warehouse) sees the requests of that warehouse only"
	)
	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": PEOPLE["approver"][0],
			"allow": "Warehouse",
			"for_value": warehouses[1],
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	p = Person("approver")
	seen = names_in(p.listing(REQUEST))
	say(
		"perm-r2" in seen and "perm-r1" not in seen,
		f"the approver limited to {warehouses[1]} lists {sorted(seen & {'perm-r1', 'perm-r2'})}",
	)
	say(
		p.form(REQUEST, "perm-r1").status_code == 403,
		"and cannot open the other warehouse's request by its name",
	)
	say(p.form(REQUEST, "perm-r2").status_code == 200, "but can open their own")
finally:
	cleanup()
	forget_people()
	frappe.db.commit()

print()
print("ALL PASSED" if not failed else f"{len(failed)} FAILED")
for what in failed:
	print("  -", what)
sys.exit(1 if failed else 0)
