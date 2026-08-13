# TicketHub Notifications service — Python stdlib stub (Ch 10-12, 16).
# Real service is a Kafka CONSUMER (subscribes orders.*, payments.*) and is
# scaled by KEDA on consumer-group lag. This stub simulates the consume loop in
# a background thread and still exposes /healthz + /readyz for K8s probes.
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KAFKA_BROKERS = "kafka-0.kafka.data:9092"  # illustrative; real value via ConfigMap
processed = 0


def consume_loop():
    """Simulated Kafka consumer — replace with a real client in production."""
    global processed
    while True:
        # In reality: poll a batch from Kafka, send email/SMS, commit offset.
        time.sleep(5)
        processed += 1


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
        elif self.path.rstrip("/") == "/api/notifications":
            self._send(200, {"service": "notifications", "processed": processed,
                             "brokers": KAFKA_BROKERS})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    threading.Thread(target=consume_loop, daemon=True).start()
    print(f"notifications consumer started (brokers={KAFKA_BROKERS}); health on :8080", flush=True)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
