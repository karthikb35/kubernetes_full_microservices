# TicketHub Services

One folder per microservice. Each ships a production Dockerfile (multi-stage,
minimal base, non-root) per **Chapter 10** of the textbook.

| Service | Language | Base pattern | Kind (Ch 11) |
|---------|----------|--------------|--------------|
| `frontend` | Node/React | build → `nginx-unprivileged` | Deployment |
| `gateway` | Go | build → `distroless/static` | Deployment |
| `orders` | Go | build → `distroless/static` | Deployment |
| `users` | Python | `python:3.12-slim`, non-root | Deployment |
| `catalog` | Python | `python:3.12-slim`, non-root | Deployment |
| `inventory` | Python | `python:3.12-slim`, non-root | Deployment |
| `payments` | Python | `python:3.12-slim`, non-root | Deployment |
| `notifications` | Python | `python:3.12-slim`, non-root | Deployment (KEDA) |
| `search` | Python | `python:3.12-slim`, non-root | Deployment |

The repo ships **two reference patterns**:

- **Go** (`gateway`, `orders`) — a multi-stage build compiling a static binary into
  `distroless/static:nonroot`. `orders/` is the full reference: `cmd/orders/main.go`
  with `/healthz`, `/readyz`, an `/api/...` handler, Prometheus metrics, and OTel traces.
- **Python** (`users`, `catalog`, `inventory`, `payments`, `notifications`, `search`) —
  a single self-contained `app.py` using only the standard library (no external deps →
  reproducible with no lockfile), copied into a non-root `python:3.12-slim` image. Each
  exposes `/healthz`, `/readyz`, and its domain endpoint. `catalog` serves the events the
  frontend renders; `notifications` simulates a Kafka consumer loop (KEDA-scaled, Ch 16).

`frontend/` uses the Node build → unprivileged-NGINX runtime pattern.

Run any Python stub directly — no install needed:

```bash
cd services/catalog && python app.py     # serves :8080/api/catalog/events
```

Build + scan + sign in CI (Ch 10 / Ch 24):

```bash
SVC=orders; SHA=$(git rev-parse --short HEAD)
docker build -t registry.internal/tickethub/$SVC:$SHA services/$SVC
trivy image --exit-code 1 --severity HIGH,CRITICAL registry.internal/tickethub/$SVC:$SHA
cosign sign --key cosign.key registry.internal/tickethub/$SVC:$SHA
docker push registry.internal/tickethub/$SVC:$SHA
```
