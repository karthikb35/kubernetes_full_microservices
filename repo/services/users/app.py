# TicketHub Users/Auth service — Python stdlib stub (Ch 10-12).
# Real service issues JWTs against PostgreSQL users_db; this stub fakes it.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERS = [{"id": 1, "email": "demo@tickethub.io", "name": "Demo User"}]


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
        elif self.path.rstrip("/") == "/api/users":
            self._send(200, {"service": "users", "users": USERS})
        elif self.path.rstrip("/") == "/api/users/verify":
            self._send(200, {"valid": True, "sub": USERS[0]["email"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") == "/api/users/login":
            self._send(200, {"token": "stub.jwt.token", "sub": USERS[0]["email"]})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("users listening on :8080", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
