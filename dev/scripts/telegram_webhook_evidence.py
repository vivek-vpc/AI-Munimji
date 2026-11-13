# What a real run of Telegram in webhook mode left on this site, so that the run can be shown and not only said: where Telegram says it delivers, what it could not deliver, the messages that were
# sent and the updates that came back, and the requests that were answered through Telegram and the draft orders they made. Read-only (one call to Telegram: getWebhookInfo).
#   SITE=<site> bash dev/run-script.sh dev/scripts/telegram_webhook_evidence.py
# Prints no token and no secret, and only the last three digits of a chat number.
import json

from ai_munimji.telegram import channel as channel_module
from ai_munimji.telegram import config

print(
	f"Telegram on: {config.on()} | mode: {config.mode()} | the address this site registers: {config.webhook_url()}"
)
channel = channel_module.build_channel()
if channel is None:
	print("no bot token on this site: nothing to ask Telegram")
else:
	info = channel.webhook_info()
	print("--- what Telegram says about the webhook (getWebhookInfo)")
	for key in (
		"url",
		"pending_update_count",
		"max_connections",
		"has_custom_certificate",
		"ip_address",
		"last_error_date",
		"last_error_message",
		"last_synchronization_error_date",
	):
		if key in info:
			print(f"  {key}: {config.hide_secrets(str(info[key]))}")
	if not info.get("last_error_message"):
		print("  (Telegram reports no delivery error)")

print("--- the people who connected a chat")
for link in frappe.get_all("Munimji Telegram Link", fields=["user", "chat_id", "enabled", "linked_on"]):
	print(
		f"  {link.user} | chat ...{str(link.chat_id)[-3:]} | requests wanted: {link.enabled} | linked {link.linked_on}"
	)

print("--- messages the site sent to Telegram, by state")
for row in frappe.db.sql(
	"select status, count(*) from `tabMunimji Approval Delivery` where channel='telegram' group by status"
):
	print(f"  {row[0]}: {row[1]}")

print("--- updates Telegram delivered and the site handled (the ledger of handled ids)")
seen = frappe.db.sql("select count(*), min(seen_at), max(seen_at) from `tabMunimji Inbound Seen`")[0]
print(f"  {seen[0]} update(s); first {seen[1]}, last {seen[2]}")

print("--- requests answered through Telegram")
answered = 0
for name in frappe.get_all(
	"Munimji Approval Request", filters={"status": ["!=", "pending"]}, pluck="name", order_by="decided_at asc"
):
	row = frappe.db.get_value(
		"Munimji Approval Request",
		name,
		["kind", "status", "approver", "decided_at", "decision_json"],
		as_dict=True,
	)
	try:
		decision = json.loads(row.decision_json or "{}")
	except ValueError:
		decision = {}
	if "telegram" in json.dumps(decision).lower():
		answered += 1
		print(f"  {name} | {row.kind} | {row.status} | by {row.approver} | {row.decided_at}")
print(f"  {answered} request(s) answered through Telegram")

print("--- the draft Purchase Orders the requests made")
for po in frappe.get_all(
	"Purchase Order",
	filters={"custom_agent_ref": ["is", "set"]},
	fields=[
		"name",
		"supplier",
		"docstatus",
		"grand_total",
		"custom_agent_ref",
		"custom_agent_approved_by",
		"creation",
	],
	order_by="creation asc",
):
	print(
		f"  {po.name} | {po.supplier} | {'draft' if po.docstatus == 0 else 'docstatus ' + str(po.docstatus)} | {po.grand_total} | from {po.custom_agent_ref} | approved by {po.custom_agent_approved_by}"
	)
