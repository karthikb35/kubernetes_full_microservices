# TicketHub Inventory service — Python stdlib stub (Ch 10-12).
# Real service manages short-lived seat holds in Redis + PostgreSQL.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOLDS = [{"event_id": 1, "seat": "A12", "held_for": "order-1001", "ttl_seconds": 120}]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/healthz", "/readyz"):
            self._send(200, {"status": "ok"})
        elif self.path.rstrip("/") == "/api/inventory":
            self._send(200, {"service": "inventory", "holds": HOLDS})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("inventory listening on :8080", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
