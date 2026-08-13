# TicketHub Payments service — Python stdlib stub (Ch 10-12).
# Real service integrates Stripe (authorize/capture/refund) over gRPC.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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
        elif self.path.rstrip("/") == "/api/payments":
            self._send(200, {"service": "payments", "provider": "stripe", "status": "stub"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") == "/api/payments/authorize":
            self._send(200, {"authorized": True, "payment_id": "pay_stub_001"})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("payments listening on :8080", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
