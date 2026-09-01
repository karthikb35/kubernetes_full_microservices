## <a name="ch10"></a>10. Containerizing the Services — Dockerfiles Done Right

The platform is running; now we ship code onto it. Every one of TicketHub's 9 services becomes a **container image**. How you build that image decides your **security posture, image size, cold-start speed, and supply-chain trust**. This chapter builds production-grade Dockerfiles from first principles.

### 10.1 What a container image actually is

An image is not a VM — it's a **stack of read-only layers** plus metadata (the `ENTRYPOINT`, the `USER`, environment). At runtime the container adds one thin **writable layer** on top.

![Image anatomy](assets/diagrams/10-image-anatomy.png)

| Property | Consequence for the architect |
|----------|-------------------------------|
| Layers are **cached** | Order Dockerfile steps least-changing → most-changing |
| Layers are **shared** | A common base image is downloaded once per node |
| Writable layer is **ephemeral** | Anything not on a volume is lost on restart |

!!! mental "Mental model — a printed book vs. scratch paper"
    The image layers are the **printed pages** of a book — fixed, shared by every
    reader. The writable container layer is a **sheet of scratch paper** clipped on top:
    you can scribble on it, but it's thrown away when the container dies. Durable data
    goes to a **volume** (Chapter 14), never the scratch paper.

### 10.2 Multi-stage builds — the single most important technique

A naive Dockerfile ships the entire build toolchain (compilers, `node_modules` with dev deps, package managers) inside the running image — bloated and full of attack surface. **Multi-stage builds** compile in one stage and copy only the finished artifact into a tiny runtime stage.

![Multi-stage build](assets/diagrams/10-multistage-build.png)

Here is TicketHub's **Orders** service (Go) as a multi-stage build:

```dockerfile
# repo/services/orders/Dockerfile
# ---- Stage 1: build ----
FROM golang:1.25 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download                 # cached unless deps change
COPY . .
RUN CGO_ENABLED=0 go build -o /out/orders ./cmd/orders

# ---- Stage 2: runtime (distroless, non-root) ----
FROM gcr.io/distroless/static:nonroot
COPY --from=builder /out/orders /orders
USER 65532:65532                    # 'nonroot' uid, never root
EXPOSE 8080
ENTRYPOINT ["/orders"]
```

The **API Gateway** (Go) follows the same distroless pattern — it's a pure stdlib reverse proxy so the final image has zero external dependencies:

```dockerfile
# repo/services/gateway/Dockerfile
FROM golang:1.22 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/gateway ./cmd/gateway

FROM gcr.io/distroless/static:nonroot
COPY --from=builder /out/gateway /gateway
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/gateway"]
```

And the **Frontend** (Node/React) service, build → unprivileged NGINX runtime:

```dockerfile
# repo/services/frontend/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install                     # installs deps from package.json
COPY . .
RUN npm run build                   # Vite produces dist/

FROM nginxinc/nginx-unprivileged:1.27-alpine   # runs as non-root by design
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
```

!!! key "Four Dockerfile rules every TicketHub image obeys"
    1. **Multi-stage** — the SDK never ships to production.
    2. **Minimal base** — `distroless` or `-alpine`; no shell, no package manager = tiny attack surface.
    3. **Non-root `USER`** — a compromised process isn't uid 0 (pairs with `runAsNonRoot`, Chapter 20).
    4. **Pin versions + use lockfiles** — `go.sum` / `package-lock.json` for reproducible, auditable builds.

### 10.3 Distroless vs. Alpine vs. full OS

| Base | Size | Shell? | When to use |
|------|------|--------|-------------|
| `distroless/static` | ~2 MB | none | Static Go/Rust binaries (best) |
| `alpine` | ~7 MB | `/bin/sh` | Needs libc/tools, still small |
| `debian-slim` | ~75 MB | full | Glibc/native deps required |
| full `ubuntu` | ~180 MB | full | Avoid for services |

Smaller isn't just disk — it's **fewer CVEs to patch** and **faster pulls** during a scale-up or node failure.

### 10.4 The build → trust → run supply chain

An image isn't trusted just because it built. In production every image is **scanned** for CVEs and **signed**, and the cluster verifies the signature before running it (enforced in Chapter 24).

![Build supply chain](assets/diagrams/10-build-supply-chain.png)

```bash
# In CI, per service:
docker build -t registry.internal/tickethub/orders:$(git rev-parse --short HEAD) .
trivy image --exit-code 1 --severity HIGH,CRITICAL registry.internal/tickethub/orders:$SHA
cosign sign --key cosign.key registry.internal/tickethub/orders:$SHA
docker push registry.internal/tickethub/orders:$SHA
```

!!! warning "Never deploy the `latest` tag to production"
    `latest` is a moving target — two nodes can pull *different* images under the same
    name, and rollbacks become guesswork. Deploy an **immutable tag** (git SHA) or, best,
    the **image digest** (`@sha256:...`). Reproducibility and rollback depend on it.

### 10.5 The private registry — where images live and how the cluster pulls them

Every image so far has been named `registry.internal/tickethub/...`. That prefix is not decoration — it's the hostname of **TicketHub's own container registry**, a service the platform team runs. On bare metal there's no cloud registry handed to you; you host one (Harbor, or the CNCF **Distribution** `registry:2`) so images never depend on Docker Hub being up or rate-limiting your node pulls, and so every image can be **scanned and signed** under your control.

![Private registry pull flow](assets/diagrams/10-private-registry.png)

Pushing is what CI does (previous section). **Pulling** is the part beginners miss: when the scheduler places a pod, the **kubelet** on that node pulls the image — and a private registry demands credentials. Anonymous pulls get `ErrImagePull` / `ImagePullBackOff`. You give the kubelet those credentials with an **imagePullSecret**: a Secret of type `kubernetes.io/dockerconfigjson`.

```bash
# Create the registry credential Secret in the namespace that needs it.
kubectl create secret docker-registry registry-internal \
  --namespace tickethub \
  --docker-server=registry.internal \
  --docker-username=ci-puller \
  --docker-password="$REGISTRY_TOKEN"
```

You can reference it two ways:

```yaml
# (a) Per pod — explicit, but repeated in every workload:
spec:
  imagePullSecrets:
    - name: registry-internal
  containers:
    - name: orders
      image: registry.internal/tickethub/orders:v1
```

```yaml
# (b) Better — attach it once to the namespace's default ServiceAccount, so
#     EVERY pod in the namespace inherits it with no per-workload change:
#     repo/manifests/10-platform/registry-pull-secret.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
  namespace: tickethub
imagePullSecrets:
  - name: registry-internal
```

!!! key "Attach pull secrets to the ServiceAccount, not every Deployment"
    Option (b) is the pattern to reach for: one edit per namespace and every current and
    future pod can pull, with nothing to forget in individual manifests. Reserve per-pod
    `imagePullSecrets` for the odd workload that needs a *different* registry.

!!! warning "Don't commit the registry password to Git"
    A `dockerconfigjson` Secret holds a real credential. Create it with `kubectl` (above)
    or, better, manage it with **External Secrets / Sealed Secrets** (Chapters 13 & 24) so
    Git never sees the plaintext token. The manifest in the repo is only the
    **ServiceAccount attachment** — the Secret itself is created out-of-band.

### 10.6 Running services locally

All three runnable services can be started on a development machine without Docker or a cluster. Each reads its upstream addresses from environment variables and falls back to `localhost` defaults.

**Orders** (Go — with Prometheus metrics + OpenTelemetry tracing):

```bash
cd repo/services/orders
go mod tidy          # resolve indirect deps on first run
go run ./cmd/orders  # listens :8080 (API) and :9090 (metrics)
```

Test: `curl http://localhost:8080/healthz` → `ok`  
Test: `curl http://localhost:8080/api/orders` → JSON stub response

**Gateway** (Go — pure stdlib reverse proxy):

```bash
cd repo/services/gateway
# Point at wherever orders/catalog are running:
export ORDERS_URL=http://localhost:8080
export CATALOG_URL=http://localhost:8082   # stub if catalog isn't running
go run ./cmd/gateway                        # listens :8080 (gateway port)
```

Test: `curl http://localhost:8080/healthz` → `ok`  
Test: `curl http://localhost:8080/api/orders` → proxied to orders service

**Frontend** (React + Vite):

```bash
cd repo/services/frontend
npm install          # first time only
npm run dev          # Vite dev server on :3000, proxies /api → gateway :8080
```

Open `http://localhost:3000` — the UI has two tabs: **Events** (calls `/api/catalog/events`) and **Orders** (calls `/api/orders`). If the backend isn't running, each tab shows a clear "could not reach service" error rather than a blank page.

!!! tip "Full local stack"
    Run orders on `:8081`, gateway on `:8080` pointing `ORDERS_URL=http://localhost:8081`, then `npm run dev` for the frontend. The Vite proxy handles CORS automatically in dev — no browser changes needed.


### 10.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Multi-stage build cache invalidation**: Docker's layer cache is invalidated from the first changed layer downward. Copying `go.mod`/`go.sum` BEFORE `COPY . .` means `go mod download` is only re-run when dependencies change, not on every code change. This is the single biggest build-time optimization for Go services.
    - **Distroless images contain no shell** — you cannot `kubectl exec -it -- /bin/sh` into them for debugging. Instead, use ephemeral debug containers: `kubectl debug -it pod/X --image=busybox --target=go-service`. Never re-add a shell to a distroless prod image just for convenience.
    - **Non-root UID must be consistent across image layers**: if the `COPY --from=builder` copies files owned by `root` and then the `USER 1000` directive switches to non-root, the app may not be able to read its own files at runtime. Always `COPY --chown=1000:1000` in the final stage, or set ownership in the builder stage.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`latest` tag in production**: `image: myapp:latest` combined with `imagePullPolicy: Always` means every pod restart pulls a new image — including breaking changes deployed after the pod was last scheduled. Always use immutable digest tags (`sha256:...`) or semver tags in production manifests.
    - **Secret injection via build ARGs**: `ARG DB_PASSWORD` makes the secret visible in `docker history` and Docker layer cache. Secrets must be injected at **runtime** via environment variables or mounted files, never baked into the image layer.
    - **Multi-arch build assumption**: building on an ARM Mac and pushing to a registry used by x86 nodes will cause `exec format error` on pod startup. Always build for `linux/amd64` explicitly in CI, or use `docker buildx` multi-platform manifests.

!!! question "Architect Considerations"
    1. **Image registry strategy**: a private registry (registry.internal.tickethub.io) is required for images that contain proprietary business logic. Decide: run Ceph/Harbor on-cluster (adds operational burden) or use an external private registry (adds a network dependency and egress cost)?
    2. **Base image governance**: who owns the base images (`golang:1.25-alpine`, `gcr.io/distroless/base`)? A team that pulls base images without verification is vulnerable to supply-chain attacks (Chapter 24). Define a process for: base image approval, vulnerability scanning, and scheduled rebuilds when base image CVEs are published.
    3. **Build reproducibility**: a Dockerfile without pinned base image digests is not reproducible — two builds of the same commit can produce different images if the base image has been updated. Pin base images by digest in Dockerfiles for production services.
    4. **Layer size vs layer count trade-off**: fewer, larger layers are generally faster to push/pull (fewer HTTP requests) but harder to cache incrementally. For a microservice with 50 MB of dependencies and 5 MB of code, separate layers make sense; for a 500 MB monolith, reconsider the decomposition.
    5. **SBOM and CVE scanning integration**: generate a Software Bill of Materials (`syft`) and scan it with `grype` in the CI pipeline. Block merges when HIGH/CRITICAL CVEs are introduced. This is the first line of supply-chain defence (Chapter 24).

!!! success "Chapter 10 checklist"
    - Every service uses a **multi-stage** Dockerfile; SDK excluded from runtime.
    - Runtime base is **distroless/alpine**, running as a **non-root `USER`**.
    - Dependencies **pinned** with lockfiles; deps layer ordered for cache reuse.
    - CI **scans (Trivy)** and **signs (cosign)** every image.
    - Deploys reference an **immutable tag/digest**, never `latest`.
    - Images live in the **private registry**; nodes pull with an **imagePullSecret**
      attached to the namespace **ServiceAccount**.
    - **Gateway** and **Frontend** are fully runnable locally (`go run` / `npm run dev`).

---
