# TicketHub Catalog service — Python stdlib stub (Ch 10-12).
# Serves the event catalog the Frontend's "Events" tab renders (via the Gateway).
# Real service would read PostgreSQL catalog_db; this stub returns static data.
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEARCH_URL = os.getenv("SEARCH_URL", "http://localhost:8089")

EVENTS = [
    {"id": 1, "name": "Aurora — World Tour", "date": "2026-09-12", "venue": "O2 Arena"},
    {"id": 2, "name": "City FC vs United", "date": "2026-09-20", "venue": "Etihad Stadium"},
    {"id": 3, "name": "Hamilton — The Musical", "date": "2026-10-03", "venue": "Victoria Palace"},
]


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
        elif self.path.rstrip("/") in ("/api/catalog/events", "/events"):
            self._send(200, EVENTS)
        elif self.path.startswith("/api/catalog/events/"):
            eid = self.path.rsplit("/", 1)[-1]
            match = next((e for e in EVENTS if str(e["id"]) == eid), None)
            self._send(200, match) if match else self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass  # quiet default logging


if __name__ == "__main__":
    print(f"catalog listening on :8080 (search={SEARCH_URL})", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
