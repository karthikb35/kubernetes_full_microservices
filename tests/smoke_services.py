# Smoke tests for the Python service stubs (Ch 10-12).
# Launches each stub, waits for /healthz, then asserts its domain endpoint
# returns HTTP 200. Uses only the standard library (no pytest needed):
#   python -m unittest tests/smoke_services.py
import pathlib
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = 8080

# service name -> domain endpoint that must return 200
SERVICES = {
    "users": "/api/users",
    "catalog": "/api/catalog/events",
    "inventory": "/api/inventory",
    "payments": "/api/payments",
    "notifications": "/api/notifications",
    "search": "/api/search?q=fc",
}


def _get(path, timeout=1):
    url = f"http://localhost:{PORT}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read()


def _wait_ready(retries=40, delay=0.25):
    for _ in range(retries):
        try:
            if _get("/healthz")[0] == 200:
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(delay)
    return False


class TestServiceStubs(unittest.TestCase):
    def test_each_stub_serves_health_and_domain(self):
        for name, endpoint in SERVICES.items():
            with self.subTest(service=name):
                svc_dir = ROOT / "repo" / "services" / name
                proc = subprocess.Popen([sys.executable, "app.py"], cwd=svc_dir)
                try:
                    self.assertTrue(_wait_ready(), f"{name} never became healthy")
                    status, _ = _get(endpoint)
                    self.assertEqual(status, 200, f"{name} {endpoint} returned {status}")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    time.sleep(0.3)  # let the port release before the next stub


if __name__ == "__main__":
    unittest.main()
