# TicketHub — Production Kubernetes Architecture

A complete, first-principles textbook and companion codebase for designing,
installing, and operating a **production Kubernetes cluster** on bare metal —
built around **TicketHub**, a 9-microservice event-ticketing platform.

This repo contains three things:

| Folder | What it is |
|--------|-----------|
| [`docs/`](docs/) | 33-chapter textbook (Markdown) — the main content |
| [`repo/`](repo/) | Runnable companion: Kubernetes manifests, service code, Argo CD app-of-apps |
| [`assets/diagrams/`](assets/diagrams/) | ~80 architecture diagrams referenced by the chapters |

---

## Read the book

**On GitHub:** browse [`docs/`](docs/) — every chapter renders inline with diagrams.
Start at [00-front-matter.md](docs/00-front-matter.md) and read in numeric order.

**As a PDF:** grab the latest build from the
[**Releases page**](../../releases) (auto-built on every push — works on phone/tablet),
or build it yourself:

```bash
pip install markdown xhtml2pdf Pillow
python build_pdf.py          # produces k8s-architecture.pdf
```

### Reading order

1. **Part I — Design** (Ch 1–4): scenario, bare metal → VMs, topology, networking
2. **Part II — Install & Platform** (Ch 5–8): kubeadm, Cilium, MetalLB/Gateway API, storage
3. **Part III — Workloads** (Ch 9–18): namespaces, containerizing, controllers, services, config, scaling, scheduling, health
4. **Part IV — Security** (Ch 19–24): RBAC, Pod Security, NetworkPolicy, Kyverno, Falco, supply chain
5. **Part V — Operate** (Ch 25–29): CRDs, observability, backup/DR, GitOps, recap

New to Kubernetes? Start with the [Chapter 0 primer](docs/00b-prerequisites.md)
and keep the [Glossary](docs/30-appendix-glossary.md) open.

---

## Run the services locally

Three services are fully runnable without a cluster. Each reads its upstream
addresses from environment variables and falls back to `localhost`.

**Orders** (Go — Prometheus metrics + OpenTelemetry tracing):

```bash
cd repo/services/orders
go mod download
go run ./cmd/orders          # API on :8080, metrics on :9090
```

**Gateway** (Go — stdlib reverse proxy):

```bash
cd repo/services/gateway
$env:ORDERS_URL  = "http://localhost:8080"   # PowerShell; use export on bash
$env:CATALOG_URL = "http://localhost:8082"
go run ./cmd/gateway         # gateway on :8080
```

**Frontend** (React + Vite):

```bash
cd repo/services/frontend
npm install
npm run dev                  # UI on :3000, proxies /api → gateway :8080
```

See [repo/services/README.md](repo/services/README.md) for the full service catalog
and the build → scan → sign CI recipe (Chapter 10 / 24).

---

## Apply the manifests

Manifests are ordered by **bootstrap sequence** (Chapter 9) and apply top-to-bottom
against any Kubernetes cluster (kind/minikube for local testing):

```bash
kubectl apply -f repo/manifests/00-namespaces/
kubectl apply -f repo/manifests/10-platform/
kubectl apply -f repo/manifests/20-data/
kubectl apply -f repo/manifests/30-workloads/
kubectl apply -f repo/manifests/40-config/
kubectl apply -f repo/manifests/50-scaling/
kubectl apply -f repo/manifests/60-security/
kubectl apply -f repo/manifests/70-observability/
```

In production these are delivered by **Argo CD** ([repo/argocd/](repo/argocd/)),
with Git as the source of truth. See [repo/README.md](repo/README.md) for details.

---

## What's illustrative vs. runnable

This is a **teaching reference**, not a production deployment. To keep the focus on
architecture:

- **Runnable code:** `frontend`, `gateway`, `orders` (build, run, and serve locally).
- **Illustrative stubs:** `users`, `catalog`, `inventory`, `payments`, `notifications`,
  `search` ship a minimal service (health/readiness + one endpoint) and a Dockerfile
  so the manifests reference real, buildable images — but they are intentionally thin.
- **Platform components** (Cilium, MetalLB, Rook-Ceph, Prometheus, etc.) are installed
  via Helm in the book; this repo carries only the custom resources and config.

---

## License & attribution

Educational material. Third-party tools (Kubernetes, Cilium, Argo CD, etc.) are
licensed by their respective owners.
