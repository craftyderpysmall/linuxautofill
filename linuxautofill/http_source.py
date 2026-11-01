"""Receive text messages from the iPhone Shortcut."""

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)

MAX_BODY = 16 * 1024


def _parse(body, content_type):
    """Return (sender, text) from a JSON or plain text body, or None if it's malformed."""
    decoded = body.decode(errors="replace")
    if not content_type.startswith("application/json"):
        return "", decoded
    try:
        payload = json.loads(decoded)
        return str(payload.get("sender", "")), str(payload["text"])
    except (ValueError, KeyError, AttributeError):
        return None


def make_server(host, port, token, messages):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def do_POST(self):
            if self.path != "/message":
                return self._finish(404)

            supplied = self.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(supplied, f"Bearer {token}".encode()):
                return self._finish(401)

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._finish(411)
            if not 0 <= length <= MAX_BODY:
                return self._finish(413)

            parsed = _parse(self.rfile.read(length), self.headers.get("Content-Type", ""))
            if parsed is None:
                return self._finish(400)
            # Links aren't taken from texts, where "verify" links are a common scam.
            messages.put(("sms", *parsed, []))
            self._finish(204)

        def _finish(self, status):
            if status != 204:
                log.warning("sms: rejected request from %s with %d", self.client_address[0], status)
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
