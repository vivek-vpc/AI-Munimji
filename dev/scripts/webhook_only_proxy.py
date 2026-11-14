"""Lets exactly one request through to a development site: Telegram's webhook.

To try Telegram's webhook mode from a laptop, Telegram has to reach the site from the internet. A tunnel (cloudflared, ngrok) that points at the bench's web server would put the whole site
there: its sign-in page, its API, every method. This proxy stands between the tunnel and a site's own server and passes on only

    POST /api/method/ai_munimji.telegram.webhook.receive     with a body of at most 64 KB and the header X-Telegram-Bot-Api-Secret-Token

Everything else gets 404 (another path, another method, a query string), 411 (no length), 413 (too big) or 408 (the client stopped sending), and nothing is passed on. The proxy does not look at the secret: the app does (its first
statement refuses a call without it). It forwards the content type and that one header, nothing else, and logs one line per request (time, method, path, answer), never a header or a body.

    python3 dev/scripts/webhook_only_proxy.py [--listen 0.0.0.0:8003] [--site http://127.0.0.1:8002]

Run it in the development container, with the site served on its own port (`bench --site <site> serve --port 8002`, which answers that site whatever the Host header says), and point the tunnel
at the proxy's port (the container publishes 8001 to 8005 on 127.0.0.1). Development tooling: it is not part of the app.
"""

import argparse
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATH = "/api/method/ai_munimji.telegram.webhook.receive"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_BODY = 64 * 1024  # the app refuses more as well (telegram/webhook.py)
UPSTREAM_TIMEOUT = 20
DRAIN_LIMIT = (
	1024 * 1024
)  # a refused request's body is read and thrown away up to this much, so the refusal reaches a client still sending


class Proxy(BaseHTTPRequestHandler):
	site = "http://127.0.0.1:8002"
	protocol_version = "HTTP/1.1"
	timeout = 15  # a client that stops sending (headers or body) loses its connection instead of holding a thread for ever

	def log_message(self, format, *args):  # the standard log line holds the client address; ours is below
		pass

	def drain(self) -> None:
		length = self.headers.get("Content-Length", "")
		left = min(int(length), DRAIN_LIMIT) if length.isdigit() else 0
		try:
			while left > 0:
				chunk = self.rfile.read(min(left, 65536))
				if not chunk:
					break
				left -= len(chunk)
		except OSError:  # a timeout or a closed connection: nothing more to read
			pass

	def reply(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8") -> None:
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Connection", "close")
		self.end_headers()
		self.wfile.write(body)
		self.close_connection = True
		print(
			f"{time.strftime('%H:%M:%S')} {self.command} {self.path.split('?')[0][:80]} -> {status}",
			flush=True,
		)

	def do_POST(self):
		if self.path != PATH:
			self.drain()
			return self.reply(404, b"not found")
		length = self.headers.get("Content-Length")
		if length is None or not length.isdigit():
			return self.reply(411, b"length required")
		if int(length) > MAX_BODY:
			self.drain()
			return self.reply(413, b"too big")
		try:
			body = self.rfile.read(int(length))
		except OSError:  # the client stopped sending
			return self.reply(408, b"timeout")
		forward = urllib.request.Request(self.site + PATH, data=body, method="POST")
		forward.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
		if self.headers.get(SECRET_HEADER) is not None:
			forward.add_header(SECRET_HEADER, self.headers[SECRET_HEADER])
		try:
			with urllib.request.urlopen(forward, timeout=UPSTREAM_TIMEOUT) as answer:
				return self.reply(
					answer.status, answer.read(), answer.headers.get("Content-Type", "application/json")
				)
		except urllib.error.HTTPError as error:
			# the site's own refusal (403 for a wrong secret) is passed on as it is
			return self.reply(error.code, error.read(), error.headers.get("Content-Type", "application/json"))
		except Exception:
			return self.reply(502, b"the site did not answer")

	def _nothing(self):
		self.drain()
		self.reply(404, b"not found")

	do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _nothing


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--listen", default="0.0.0.0:8003")
	parser.add_argument("--site", default="http://127.0.0.1:8002")
	args = parser.parse_args()
	host, _, port = args.listen.rpartition(":")
	Proxy.site = args.site.rstrip("/")
	server = ThreadingHTTPServer((host or "0.0.0.0", int(port)), Proxy)
	print(f"passing on only POST {PATH} to {Proxy.site}; listening on {args.listen}", flush=True)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
