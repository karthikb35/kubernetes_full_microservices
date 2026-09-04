## <a name="ch12"></a>12. Services & Traffic — ClusterIP, Headless & Gateway Routing

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
| **LoadBalancer** | External IP (MetalLB) | The Gateway's Service only |

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

Put it together: north-south enters through the Gateway; east-west hops are service-to-service by DNS name — **never** a raw pod IP.

![Request path](assets/diagrams/12-request-path.png)

1. User hits `https://tickethub.example.com/api/orders` → MetalLB IP → **Gateway**.
2. The Gateway's HTTPRoute matches `/api` → **`gateway`** ClusterIP → a gateway pod.
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


### 12.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **kube-dns (CoreDNS) search domains** mean `postgres` inside a pod resolves to `postgres.<current-namespace>.svc.cluster.local`. If a pod in `tickethub` ns calls `postgres.data` (intending `postgres.data.svc.cluster.local`), it first tries `postgres.data.tickethub.svc.cluster.local` — which fails — before trying the correct form. Always use fully qualified names for cross-namespace DNS to avoid ndots resolution latency.
    - **Session affinity (`sessionAffinity: ClientIP`) is hash-based, not sticky-session aware**: all connections from the same client IP hit the same pod, but a pod restart breaks affinity. If you need application-level stickiness (shopping cart, websocket), express it as a cookie-based `HTTPRoute` filter in your Gateway implementation (or a service mesh policy), not the Service affinity.
    - **`ExternalTrafficPolicy: Local`** on a LoadBalancer Service preserves the original client IP (no SNAT) but means only nodes with a backend pod accept traffic — nodes without a pod will drop the connection. With 3 pods spread across 9 nodes, 6 out of 9 nodes will silently drop ingress traffic for that Service.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`ClusterIP: None` makes a Service headless** — it returns A records for individual pod IPs, not a virtual IP. Calling `postgres.data.svc.cluster.local` from the `orders` service returns all 3 pod IPs via DNS. If orders uses a naive HTTP client that doesn't re-resolve DNS on each connection, it may always route to the same pod. Headless Services require the client to implement its own load balancing.
    - **Service port name must match Istio/Cilium L7 protocol detection**: naming a Service port `http` vs `tcp` changes how a service mesh or L7 NetworkPolicy processes it. Cilium uses the port name to decide whether to apply HTTP-aware policy. Always name ports with the correct protocol prefix.
    - **Endpoint not ready after pod crash**: Kubernetes removes the pod's IP from the Service's EndpointSlice only after the readiness probe fails AND the pod is removed. During the gap (typically < 5s), the Service may route to a pod that is no longer serving. Ensure client retries are configured for this transient window.

!!! question "Architect Considerations"
    1. **Headless Service for StatefulSets vs ClusterIP for Deployments**: this isn't a choice — StatefulSets that need stable per-pod DNS (Kafka brokers identifying themselves as `kafka-0.kafka.data`) MUST use headless. Deployments use ClusterIP for load-balanced access. Mixing them up is a common cause of mysterious connection failures.
    2. **Service topology aware routing**: Kubernetes EndpointSlice topology hints route traffic preferentially to pods on the same node or zone. For TicketHub, routing Orders → Postgres within the same zone reduces cross-rack latency. Enable topology hints on Services where cross-AZ latency matters.
    3. **East-West load balancing algorithm**: Cilium's eBPF uses maglev consistent hashing for Service load balancing by default — which gives better connection distribution than simple round-robin, especially for long-lived gRPC connections. Verify your connection pool sizes account for this distribution.
    4. **NodePort port range**: the default NodePort range is `30000-32767`. Using NodePorts for production services is not recommended (port memorization burden, firewall complexity), but if needed for legacy integrations, document the port assignments explicitly to prevent conflicts.
    5. **Service vs Ingress for internal services**: internal services (Orders calling Payments) should use ClusterIP Services directly — they don't need Ingress. Only traffic entering from outside the cluster needs Ingress. Routing internal traffic through Ingress adds unnecessary latency and a single point of failure.

!!! success "Chapter 12 checklist"
    - Every service exposed as a **ClusterIP**; services call each other by **DNS name**.
    - StatefulSets front a **headless** Service for stable per-pod DNS.
    - Only the **Ingress controller** is a `LoadBalancer` (via MetalLB).
    - **Readiness probes** defined so only Ready pods receive traffic.
    - No raw pod IPs or ClusterIPs hard-coded anywhere.

---
