"""The whole way through Telegram, on real ERPNext data, with real people signed in over HTTP and a pretend Telegram (dev/scripts/fake_telegram.py).

    .\\dev\\telegram-e2e.ps1          (starts the pretend Telegram, points the site at it, runs this, and says what it saw)

What happens, in order, and what is checked at each step:
  1. a Munimji Manager switches Telegram on and presses Connect the bot: Telegram is asked who the token belongs to and is given the webhook and its secret;
  2. an approver presses Connect Telegram, and the pretend Telegram "presses Start" on the link: the webhook (over HTTP, as a stranger) connects the chat to that user; a call without the
     secret, or with another, is refused, and a stranger's /start gets their own chat number only;
  3. the stock check reads the contract world and makes a reorder request; a delivery job sends it to the approver's chat with its buttons; the check itself called Telegram never;
  4. the approver "presses" Start reorder: the webhook decides it as that person, the chat is tidied and told what happens next; the vendor comparison job makes the purchase request,
     which is sent;
  5. the approver presses Create order: a Draft Purchase Order exists in the approver's name; a second press is refused;
  6. the audit seal still checks out; then the site is set to polling, and a press that Telegram holds is fetched and handled by the polling loop.
It needs the contract world (dev/scripts/load_contract_world.py) on a site whose name starts with "world" and served on http://127.0.0.1:8010, the bench running with a worker restarted after
the app was last changed, and the pretend Telegram on http://127.0.0.1:8999. It makes users and records and removes them again. Development tooling: it is not part of the app.
"""

import json
import sys
import time

import requests

from ai_munimji import jobs, wiring
from ai_munimji.stores import frappe_core_stores
from ai_munimji.telegram import config, links
from ai_munimji.telegram import jobs as telegram_jobs
from ai_munimji.tests.helpers import empty_store_tables
from ai_munimji.tests.world import described

BASE, FAKE = (
	"http://127.0.0.1:8010",
	"http://127.0.0.1:8999",
)  # the site's own server (dev/telegram-e2e.ps1 starts it: the bench's, on 8000, serves the default site whatever the Host says)
SITE = frappe.local.site
PASSWORD = "Munimji-dev-1!"
TOKEN = "424242:AAE2E-pretend-token-not-a-secret"
PEOPLE = {
	"manager": ("e2e.manager@example.com", ("Munimji Manager", "Purchase User", "Stock User")),
	"alice": (
		"e2e.alice@example.com",
		("Munimji Approver", "Purchase User", "Purchase Manager", "Stock User"),
	),
}
CHAT = "7001"
STRANGER = "7999"
WEBHOOK_PATH = "/api/method/ai_munimji.telegram.webhook.receive"
failed: list[str] = []


def say(ok: bool, what: str) -> None:
	print(("  PASS  " if ok else "  FAIL  ") + what, flush=True)
	if not ok:
		failed.append(what)


def fake(path: str = "/control/state", **body):
	response = requests.post(FAKE + path, json=body) if body else requests.get(FAKE + path)
	return response.json()


def to_the_webhook(update: dict, secret: str | None) -> requests.Response:
	"""What Telegram does: a POST to the site's address, from nobody in particular, with the secret in a header."""
	headers = {"Host": SITE, "Content-Type": "application/json"}
	if secret is not None:
		headers["X-Telegram-Bot-Api-Secret-Token"] = secret
	return requests.post(BASE + WEBHOOK_PATH, data=json.dumps(update), headers=headers)


class Person:
	def __init__(self, key: str) -> None:
		self.email = PEOPLE[key][0]
		self.http = requests.Session()
		self.http.headers["Host"] = SITE
		login = self.http.post(f"{BASE}/api/method/login", data={"usr": self.email, "pwd": PASSWORD})
		assert login.status_code == 200, (self.email, login.status_code, login.text[:200])
		page = self.http.get(f"{BASE}/app")
		marker = 'csrf_token = "'
		self.csrf = page.text.split(marker, 1)[1].split('"', 1)[0] if marker in page.text else ""

	def call(self, method: str, **body) -> dict:
		response = self.http.post(
			f"{BASE}/api/method/{method}", json=body or None, headers={"X-Frappe-CSRF-Token": self.csrf}
		)
		return response.json().get("message", response.json())


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


def settings(**values) -> None:
	page = frappe.get_doc("AI Munimji Settings")
	for key, value in values.items():
		page.set(key, value)
	page.save()
	frappe.clear_document_cache("AI Munimji Settings", "AI Munimji Settings")


def buttons_of(message: dict) -> list[str]:
	return [label for row in message["buttons"] for label in row]


def messages_to(chat: str) -> list[dict]:
	return [m for m in fake()["messages"] if m["chat_id"] == chat]


def press(chat: str, message: dict, label: str) -> requests.Response:
	flat_buttons = [b for row in message["buttons"] for b in row]
	flat_callbacks = [c for row in message["callbacks"] for c in row]
	data = flat_callbacks[flat_buttons.index(label)]
	update = {
		"update_id": int(time.time() * 1000) % 10**9,
		"callback_query": {"id": f"cq{time.time_ns()}", "from": {"id": int(chat)}, "data": data},
	}
	return to_the_webhook(update, config.webhook_secret())


def deliver() -> dict:
	"""The delivery job, as a worker runs it: its work is kept when it returns (the server must see the messages it recorded)."""
	out = telegram_jobs.deliver_new()
	frappe.db.commit()
	return out


def decision_of(approval_id: str):
	row = frappe_core_stores(system=True).approvals.get(approval_id)
	return json.loads(row["decision_json"]) if row and row["decision_json"] else None


def main() -> int:
	world = described()
	if not SITE.startswith("world") or not world:
		print(
			f"This script needs the contract world on a site whose name starts with 'world' (this is {SITE})."
		)
		return 2
	if not (frappe.conf.get("ai_munimji_telegram_api_base") or "").startswith(
		"http://127.0.0.1:8999"
	) or not (frappe.conf.get("host_name") or "").startswith("https://"):
		print(
			"Point the site at the pretend Telegram first:  .\\dev\\telegram-e2e.ps1  does it (ai_munimji_telegram_api_base and an https host_name)."
		)
		return 2
	steady = world["names"]["steady"]
	frappe.set_user("Administrator")
	empty_store_tables()
	make_people()
	settings(enabled=1, min_qty=300, min_days_cover=0, stock_alerts=0, telegram_enabled=0)
	frappe.db.commit()
	fake("/control/reset", reset=True)
	manager, alice = Person("manager"), Person("alice")

	print("1. the manager connects the bot")
	settings(telegram_enabled=1, telegram_bot_token=TOKEN, telegram_mode="Webhook")
	frappe.db.commit()
	out = manager.call("ai_munimji.telegram.api.connect_bot")
	say(bool(out.get("ok")), f"Connect the bot: {out.get('message')}")
	hook = fake()["webhook"] or {}
	say(
		hook.get("url") == config.webhook_url() and hook.get("secret_token") == config.webhook_secret(),
		"Telegram was given the site's webhook address and its secret",
	)
	say(TOKEN not in json.dumps(out), "the answer to the page does not hold the token")
	say(
		frappe.db.get_single_value("AI Munimji Settings", "telegram_bot_username") == "munimji_demo_bot",
		"the bot's name was kept",
	)

	print("2. the approver connects her chat; strangers and wrong secrets are refused")
	connect = alice.call("ai_munimji.telegram.api.connect")
	say(
		bool(connect.get("ok")) and connect["link"].startswith("https://t.me/munimji_demo_bot?start="),
		"Connect Telegram gives a link to the bot with a code",
	)
	code = connect["link"].split("start=", 1)[1]
	say(
		to_the_webhook(
			{
				"update_id": 1,
				"message": {
					"text": f"/start {code}",
					"from": {"id": 7001},
					"chat": {"id": 7001, "type": "private"},
				},
			},
			None,
		).status_code
		== 403,
		"a call without the secret is refused (403)",
	)
	say(
		to_the_webhook(
			{
				"update_id": 2,
				"message": {
					"text": f"/start {code}",
					"from": {"id": 7001},
					"chat": {"id": 7001, "type": "private"},
				},
			},
			"wrong",
		).status_code
		== 403,
		"a call with the wrong secret is refused (403)",
	)
	say(not messages_to(CHAT), "and the bot said nothing")
	start = {
		"update_id": 3,
		"message": {
			"message_id": 1,
			"text": f"/start {code}",
			"from": {"id": int(CHAT), "is_bot": False, "first_name": "Alice"},
			"chat": {"id": int(CHAT), "type": "private"},
		},
	}
	answered = to_the_webhook(start, config.webhook_secret())
	say(answered.status_code == 200, "Start with the code is accepted")
	frappe.db.rollback()  # see what the server committed
	say(
		frappe.db.get_value("Munimji Telegram Link", PEOPLE["alice"][0], "chat_id") == CHAT,
		"the chat is now Alice's",
	)
	say(
		any(m["text"].startswith("Connected.") for m in messages_to(CHAT)),
		"the bot told her she is connected",
	)
	say(alice.call("ai_munimji.telegram.api.connection").get("connected") is True, "the dialog sees it")
	to_the_webhook(
		{
			"update_id": 4,
			"message": {
				"text": "/start",
				"from": {"id": int(STRANGER), "is_bot": False},
				"chat": {"id": int(STRANGER), "type": "private"},
			},
		},
		config.webhook_secret(),
	)
	[hello] = messages_to(STRANGER)
	say(
		STRANGER in hello["text"] and CHAT not in hello["text"],
		"a stranger who writes is told their own chat number and nothing else",
	)

	print("3. the stock check makes a request; a job sends it")
	before = len(fake()["calls"])
	frappe.set_user("Administrator")
	report = jobs.run_stock_check(items=[steady])
	say(
		report["ran"] and report["alerts"] == 1,
		f"the stock check raised a reorder ({report['alerts']} alert)",
	)
	say(len(fake()["calls"]) == before, "the stock check itself made no call to Telegram")
	say(deliver()["sent"] == 1, "the delivery job sent it to one person")
	[reorder_message] = [m for m in messages_to(CHAT) if "Start reorder" in buttons_of(m)]
	say(
		bool(reorder_message),
		f"her chat has the request with its buttons: {buttons_of(reorder_message)}",
	)
	reorder_id = reorder_message["callbacks"][0][0].split("|")[1]

	print("4. she presses Start reorder")
	answered = press(CHAT, reorder_message, "Start reorder")
	say(answered.status_code == 200, "the webhook accepted the press")
	frappe.db.rollback()
	decision = decision_of(reorder_id)
	say(
		bool(decision) and decision["actor_id"] == PEOPLE["alice"][0] and decision["channel"] == "telegram",
		f"it is recorded as Alice's own answer via telegram: {decision and (decision['actor_id'], decision['channel'])}",
	)
	state = fake()
	say(
		any("Recorded: Start reorder" in m["text"] for m in messages_to(CHAT)),
		"the chat shows what was recorded",
	)
	say(
		next(m for m in state["messages"] if m["message_id"] == reorder_message["message_id"])[
			"buttons_removed"
		],
		"the buttons are gone from the request",
	)
	say(
		any(m["text"].startswith("Approved. The vendors are being compared") for m in messages_to(CHAT)),
		"and one plain sentence says what happens next",
	)
	(work_order,) = frappe_core_stores(system=True).workorders.list("pending", "REORDER_NEEDED", 10)
	frappe.set_user("Administrator")
	jobs.run_vendor_comparison(work_order["id"])
	say(
		deliver()["sent"] == 1,
		"the vendor comparison made the purchase request, and it was sent",
	)
	[order_message] = [m for m in messages_to(CHAT) if "Create order" in buttons_of(m)]
	order_id = order_message["callbacks"][0][0].split("|")[1]

	print("5. she presses Create order")
	answered = press(CHAT, order_message, "Create order")
	say(answered.status_code == 200, "the webhook accepted the press")
	frappe.db.rollback()
	proposal = wiring.build(jobs.system_erp(), jobs.system_stores()).proposals.by_approval(order_id)
	po = proposal.po_name if proposal else None
	say(
		bool(po) and frappe.db.get_value("Purchase Order", po, "docstatus") == 0,
		f"a Draft Purchase Order was made: {po}",
	)
	say(
		bool(po) and frappe.db.get_value("Purchase Order", po, "owner") == PEOPLE["alice"][0],
		"in Alice's name",
	)
	say(
		any(
			m["text"] == f"Draft Purchase Order {po} made. Review and submit it in ERPNext."
			for m in messages_to(CHAT)
		),
		"and the chat says so, with the number",
	)
	toasts_before = len(fake()["toasts"])
	press(CHAT, order_message, "Create order")
	say(
		fake()["toasts"][toasts_before:][-1].startswith("Already answered")
		if len(fake()["toasts"]) > toasts_before
		else False,
		"a second press is refused",
	)
	frappe.db.rollback()
	say(frappe.db.count("Purchase Order", {"name": po}) == 1, "and no second order was made")

	print("6. the seal, then polling")
	frappe.set_user("Administrator")
	jobs.run_stock_check(items=[steady])
	verdict = wiring.build(jobs.system_erp(), jobs.system_stores()).audit.verify()
	say(bool(verdict["ok"]), f"the audit seal checks out ({verdict['entries']} entries)")
	settings(telegram_mode="Polling")
	frappe.db.commit()
	say(
		bool(manager.call("ai_munimji.telegram.api.connect_bot").get("ok")),
		"Connect the bot in polling mode clears the webhook",
	)
	say(fake()["webhook"] is None, "Telegram holds no webhook now")
	others = [n for n in world["names"].values() if n.startswith("CT-") and n != steady][:6]
	frappe.set_user("Administrator")
	report = jobs.run_stock_check(items=others)
	say(report["ran"], f"another stock check ({report['alerts']} alerts)")
	deliver()
	waiting = [m for m in messages_to(CHAT) if "Start reorder" in buttons_of(m) and not m["buttons_removed"]]
	say(bool(waiting), f"{len(waiting)} more request(s) reached her chat")
	if waiting:
		target = waiting[-1]
		data = [c for row in target["callbacks"] for c in row][
			[b for row in target["buttons"] for b in row].index("Details")
		]
		fake("/control/queue", callback_query={"id": "cqpoll", "from": {"id": int(CHAT)}, "data": data})
		telegram_jobs.LOOP_SECONDS = 4
		frappe.db.commit()  # the loop takes its lease first, and the lease refuses a transaction that has work in it
		out = telegram_jobs.poll()
		say(
			out.get("ran") is True and out.get("handled", 0) >= 1,
			f"the polling loop fetched and handled the press: {out}",
		)
		say("Details sent" in fake()["toasts"], "and she was answered")
		time.sleep(0.2)

	print("cleaning up")
	frappe.set_user("Administrator")
	settings(telegram_enabled=0)
	for email, _roles in PEOPLE.values():
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	if po and frappe.db.exists("Purchase Order", po):
		frappe.delete_doc("Purchase Order", po, force=True, ignore_permissions=True)
	empty_store_tables()
	frappe.db.commit()
	print()
	print(f"{len(failed)} check(s) failed" if failed else "all checks passed")
	return 1 if failed else 0


code = main()
if code:
	sys.exit(code)
