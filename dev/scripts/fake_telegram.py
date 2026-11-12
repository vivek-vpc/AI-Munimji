"""A pretend Telegram, to try AI Munimji's Telegram connection without a bot, a token or the internet.

    python dev/scripts/fake_telegram.py [--port 8999]

It answers the part of Telegram's Bot API that the app uses (`POST /bot<token>/<method>`): getMe, sendMessage, editMessageReplyMarkup, answerCallbackQuery, setWebhook, deleteWebhook,
getWebhookInfo and getUpdates. Like the real one it refuses a webhook that is not HTTPS, and refuses getUpdates while a webhook is set (409). It keeps everything it was sent, and a person
looks at it, or a test asks, through a small control interface of its own (not Telegram's):

    GET  /control/state     everything: the messages as the chats would show them, the toasts, the calls, the webhook (with the secret it was given)
    POST /control/queue     queue an update for getUpdates (JSON body = the update; update_id is made if missing)
    POST /control/forward   do what Telegram does with a webhook: POST {"update": {...}, "to": "http://127.0.0.1:8010"} sends the update to the path of the webhook it was given, on the
                            address in "to" (the registered one is a pretend https address), with the secret it was given in the header. Answers with the status the site gave
    POST /control/reset     forget everything

The app is pointed at it with the site's own configuration, which no page can change:  bench --site <site> set-config ai_munimji_telegram_api_base http://127.0.0.1:8999
Nothing here is used by the app itself.
"""

import argparse
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()


def fresh() -> dict:
	return {
		"messages": [],
		"toasts": [],
		"calls": [],
		"webhook": None,
		"queue": [],
		"next_message": 1000,
		"next_update": 5000,
	}


STATE = fresh()
BOT = {"id": 424242, "is_bot": True, "first_name": "AI Munimji demo", "username": "munimji_demo_bot"}


def bot_error(code: int, description: str) -> tuple[int, dict]:
	return code, {"ok": False, "error_code": code, "description": description}


def handle(method: str, payload: dict, token: str) -> tuple[int, dict]:
	with LOCK:
		STATE["calls"].append({"method": method, "payload": payload, "at": time.time()})
		if method == "getMe":
			return 200, {"ok": True, "result": BOT}
		if method == "sendMessage":
			chat, text = payload.get("chat_id"), payload.get("text")
			if not chat or not text:
				return bot_error(400, "Bad Request: chat_id and text are required")
			STATE["next_message"] += 1
			message = {
				"message_id": STATE["next_message"],
				"chat_id": str(chat),
				"text": text,
				"buttons": [
					[b["text"] for b in row]
					for row in (payload.get("reply_markup") or {}).get("inline_keyboard", [])
				],
				"callbacks": [
					[b["callback_data"] for b in row]
					for row in (payload.get("reply_markup") or {}).get("inline_keyboard", [])
				],
				"reply_to": payload.get("reply_to_message_id"),
				"buttons_removed": False,
			}
			STATE["messages"].append(message)
			return 200, {"ok": True, "result": {"message_id": message["message_id"], "chat": {"id": chat}}}
		if method == "editMessageReplyMarkup":
			for message in STATE["messages"]:
				if message["message_id"] == payload.get("message_id") and message["chat_id"] == str(
					payload.get("chat_id")
				):
					message["buttons_removed"] = not (payload.get("reply_markup") or {}).get(
						"inline_keyboard"
					)
			return 200, {"ok": True, "result": True}
		if method == "answerCallbackQuery":
			STATE["toasts"].append(payload.get("text", ""))
			return 200, {"ok": True, "result": True}
		if method == "setWebhook":
			if not str(payload.get("url", "")).startswith("https://"):
				return bot_error(400, "Bad Request: bad webhook: An HTTPS URL must be provided for webhook")
			STATE["webhook"] = {"url": payload["url"], "secret_token": payload.get("secret_token")}
			return 200, {"ok": True, "result": True, "description": "Webhook was set"}
		if method == "deleteWebhook":
			STATE["webhook"] = None
			return 200, {"ok": True, "result": True}
		if method == "getWebhookInfo":
			info = {
				"url": (STATE["webhook"] or {}).get("url", ""),
				"pending_update_count": len(STATE["queue"]),
			}
			return 200, {"ok": True, "result": info}
		if method == "getUpdates":
			if STATE["webhook"]:
				return bot_error(
					409,
					"Conflict: can't use getUpdates method while webhook is active; use deleteWebhook to delete the webhook first",
				)
			offset = int(payload.get("offset") or 0)
			STATE["queue"] = [u for u in STATE["queue"] if u["update_id"] >= offset]
	if method == "getUpdates":
		waited = 0.0
		while waited < min(float(payload.get("timeout") or 0), 2.0):
			with LOCK:
				if STATE["queue"]:
					break
			time.sleep(0.1)
			waited += 0.1
		with LOCK:
			return 200, {"ok": True, "result": list(STATE["queue"])}
	return bot_error(404, f"Not Found: {method}")


class Handler(BaseHTTPRequestHandler):
	def log_message(self, *args):  # quiet
		pass

	def reply(self, status: int, body: dict) -> None:
		data = json.dumps(body).encode()
		self.send_response(status)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def body(self) -> dict:
		length = int(self.headers.get("Content-Length") or 0)
		try:
			return json.loads(self.rfile.read(length) or b"{}")
		except ValueError:
			return {}

	def do_GET(self):
		if self.path == "/control/state":
			with LOCK:
				return self.reply(200, STATE)
		self.reply(404, {"ok": False})

	def do_POST(self):
		path = self.path.split("?")[0]
		if path == "/control/reset":
			with LOCK:
				STATE.clear()
				STATE.update(fresh())
			return self.reply(200, {"ok": True})
		if path == "/control/queue":
			update = self.body()
			with LOCK:
				STATE["next_update"] += 1
				update.setdefault("update_id", STATE["next_update"])
				STATE["queue"].append(update)
			return self.reply(200, {"ok": True, "update_id": update["update_id"]})
		if path == "/control/forward":
			asked = self.body()
			with LOCK:
				webhook = dict(STATE["webhook"] or {})
			if not webhook:
				return self.reply(409, {"ok": False, "description": "no webhook is registered"})
			target = asked["to"].rstrip("/") + urllib.parse.urlsplit(webhook["url"]).path
			headers = {"Content-Type": "application/json"}
			if webhook.get("secret_token"):
				headers["X-Telegram-Bot-Api-Secret-Token"] = webhook["secret_token"]
			try:
				with urllib.request.urlopen(
					urllib.request.Request(
						target, data=json.dumps(asked["update"]).encode(), headers=headers
					),
					timeout=60,
				) as response:
					status = response.status
			except urllib.error.HTTPError as error:
				status = error.code
			return self.reply(200, {"ok": True, "status": status})
		parts = path.strip("/").split("/")
		if len(parts) == 2 and parts[0].startswith("bot"):
			status, body = handle(parts[1], self.body(), parts[0][3:])
			return self.reply(status, body)
		self.reply(404, {"ok": False})


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--port", type=int, default=8999)
	parser.add_argument("--host", default="127.0.0.1")
	args = parser.parse_args()
	print(f"pretend Telegram on http://{args.host}:{args.port} (control: /control/state)", flush=True)
	ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
