## <a name="ch12"></a>12. Services & Traffic — ClusterIP, Headless & Ingress Routing

Pods are **ephemeral** — they get new IPs on every restart. If the Orders service called Payments by pod IP, it would break constantly. A **Service** solves this: a stable name and virtual IP in front of a changing set of pods. This chapter covers how traffic actually flows through TicketHub, east-west and north-south.

### 12.1 Why Services exist

![Service endpoints](assets/diagrams/12-service-endpoints.png)

A Service has a **selector** (`app: orders`). Kubernetes continuously maintains an **EndpointSlice** — the list of *Ready* pod IPs matching that selector. Cilium's eBPF datapath load-balances traffic across those IPs. When pods come, go, or fail readiness, the EndpointSlice updates automatically.

!!! mental "Mental model — a restaurant phone number"
    A Service is the restaurant's **published phone number**. Individual staff (pods)
    come and go, shifts change, but the number never does. You call the number; whoever
    is on duty and ready (passed the readiness probe) picks up. You never memorize an
    individual employee's cell (pod IP).

### 12.2 The Service types

![Service types](assets/diagrams/12-service-types.png)

| Type | Reachable from | TicketHub use |
|------|----------------|---------------|
| **ClusterIP** (default) | Inside cluster only | All 9 services talk to each other |
| **Headless** (`clusterIP: None`) | Direct per-pod DNS | StatefulSets (Postgres, Kafka) |
| **NodePort** | `nodeIP:30000–32767` | Rarely direct; building block |
| **LoadBalancer** | External IP (MetalLB) | The Ingress controller only |

The standard TicketHub Service is a plain **ClusterIP**:

```yaml
# repo/manifests/30-workloads/orders-deployment.yaml (Service section)
apiVersion: v1
kind: Service
metadata:
  name: orders
  namespace: tickethub
spec:
  selector: { app: orders }        # matches the Deployment's pod labels
  ports:
    - port: 80                      # stable virtual port
      targetPort: 8080              # container port
```

Now any pod resolves it by DNS: `http://orders.tickethub.svc.cluster.local` (or just `orders` within the same namespace).

### 12.3 Headless Services for StatefulSets

A normal ClusterIP hides individual pods behind one VIP — but a Kafka client or a Postgres replica needs to reach **a specific pod**. A **headless** Service (`clusterIP: None`) returns the pod IPs directly and gives each StatefulSet pod stable DNS: `postgres-0.postgres.data.svc.cluster.local`.

```yaml
# repo/manifests/20-data/postgres-statefulset.yaml (headless Service section)
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: data
spec:
  clusterIP: None                  # headless
  selector: { app: postgres }
  ports: [{ port: 5432 }]
```

### 12.4 The full request path

Put it together: north-south enters through the Ingress; east-west hops are service-to-service by DNS name — **never** a raw pod IP.

![Request path](assets/diagrams/12-request-path.png)

1. User hits `https://tickethub.example.com/api/orders` → MetalLB IP → **NGINX Ingress**.
2. Ingress routes `/api` → **`gateway`** ClusterIP → a gateway pod.
3. Gateway calls **`orders`** ClusterIP → an orders pod.
4. Orders queries **`postgres-0.postgres.data`** (headless) → the primary.

Each arrow is a Service. That indirection is what lets pods scale, move, and fail without breaking callers.

The **Gateway** service (`repo/services/gateway`) implements this routing as a Go reverse proxy. Upstream addresses are injected via environment variables — no hard-coded DNS names inside the binary:

```go
// repo/services/gateway/cmd/gateway/main.go (excerpt)
ordersURL  := getEnv("ORDERS_URL",  "http://localhost:8081")
catalogURL := getEnv("CATALOG_URL", "http://localhost:8082")

mux.Handle("/api/orders/",  newProxy(ordersURL,  ""))
mux.Handle("/api/catalog/", newProxy(catalogURL, ""))
```

In the cluster, the Deployment injects the real ClusterIP DNS names:

```yaml
env:
  - name: ORDERS_URL
    value: http://orders.tickethub.svc.cluster.local
  - name: CATALOG_URL
    value: http://catalog.tickethub.svc.cluster.local
```

Locally, you override them to point at whatever port your services are running on — no cluster required. This pattern (env-var upstreams, localhost fallback) is what makes the service runnable both `go run` on a laptop and inside Kubernetes without any code changes.

!!! key "DNS-based service discovery is the contract"
    Services always address each other by **DNS name**, resolved by CoreDNS (Chapter 4).
    Hard-coding pod IPs, or even ClusterIPs, is an anti-pattern — names are stable across
    restarts, rescheduling, and cluster rebuilds; IPs are not.

### 12.5 Ingress vs. Gateway API

The **Ingress** object (Chapter 7) declares host/path routing + TLS for north-south HTTP. The newer **Gateway API** (`Gateway` + `HTTPRoute`) is its successor — richer traffic splitting, header routing, and a cleaner separation between infra owners and app owners. TicketHub starts on Ingress and can adopt Gateway API per-service without disruption.

!!! warning "Readiness probes gate the EndpointSlice"
    A pod is only added to a Service's EndpointSlice once its **readiness probe** passes
    (Chapter 18). Forget the probe and traffic hits pods that are still booting →
    connection errors during every rollout and scale-up. Readiness is what makes
    zero-downtime deploys real.

!!! success "Chapter 12 checklist"
    - Every service exposed as a **ClusterIP**; services call each other by **DNS name**.
    - StatefulSets front a **headless** Service for stable per-pod DNS.
    - Only the **Ingress controller** is a `LoadBalancer` (via MetalLB).
    - **Readiness probes** defined so only Ready pods receive traffic.
    - No raw pod IPs or ClusterIPs hard-coded anywhere.

---
