# TicketHub Services

One folder per microservice. Each ships a production Dockerfile (multi-stage,
minimal base, non-root) per **Chapter 10** of the textbook.

| Service | Language | Base pattern | Kind (Ch 11) |
|---------|----------|--------------|--------------|
| `frontend` | Node/React | build → `nginx-unprivileged` | Deployment |
| `gateway` | Go | build → `distroless/static` | Deployment |
| `users` | Go | build → `distroless/static` | Deployment |
| `catalog` | Go | build → `distroless/static` | Deployment |
| `inventory` | Go | build → `distroless/static` | Deployment |
| `orders` | Go | build → `distroless/static` | Deployment |
| `payments` | Go | build → `distroless/static` | Deployment |
| `notifications` | Go | build → `distroless/static` | Deployment |
| `search` | Go | build → `distroless/static` | Deployment |

The Go services all follow the **`orders/`** reference implementation:
`cmd/<svc>/main.go` exposing `/healthz`, `/readyz`, and an `/api/...` handler,
built by an identical multi-stage `Dockerfile`. `frontend/` uses the Node build
→ unprivileged-NGINX runtime pattern.

Build + scan + sign in CI (Ch 10 / Ch 24):

```bash
SVC=orders; SHA=$(git rev-parse --short HEAD)
docker build -t registry.internal/tickethub/$SVC:$SHA services/$SVC
trivy image --exit-code 1 --severity HIGH,CRITICAL registry.internal/tickethub/$SVC:$SHA
cosign sign --key cosign.key registry.internal/tickethub/$SVC:$SHA
docker push registry.internal/tickethub/$SVC:$SHA
```
