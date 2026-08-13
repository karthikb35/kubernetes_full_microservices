# TicketHub Search service — Python stdlib stub (Ch 10-12).
# Real service indexes events in an object store + search index (VPA-scaled, Ch 16).
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

INDEX = ["Aurora — World Tour", "City FC vs United", "Hamilton — The Musical"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/healthz", "/readyz"):
            self._send(200, {"status": "ok"})
        elif parsed.path.rstrip("/") == "/api/search":
            q = (parse_qs(parsed.query).get("q") or [""])[0].lower()
            results = [e for e in INDEX if q in e.lower()] if q else INDEX
            self._send(200, {"service": "search", "query": q, "results": results})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("search listening on :8080", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
