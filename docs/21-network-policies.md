## <a name="ch21"></a>21. Network Policies — Zero-Trust Segmentation with Cilium

By default, **every pod in a Kubernetes cluster can talk to every other pod** — a flat, open network. For a platform handling payments that's unacceptable. **NetworkPolicies** turn the network zero-trust: deny everything, then allow only the flows TicketHub actually needs. Cilium (Chapter 6) enforces them in eBPF and extends them to L7.

### 21.1 The default-deny foundation

The first policy in every namespace denies all ingress and egress. From there you whitelist specific flows.

![Default deny](assets/diagrams/21-default-deny.png)

```yaml
# repo/manifests/60-security/network-policies.yaml (default-deny section)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: tickethub
spec:
  podSelector: {}                  # selects ALL pods in the namespace
  policyTypes: [Ingress, Egress]   # deny both directions by default
```

!!! mental "Mental model — office doors that default to locked"
    Out of the box the cluster is an **open-plan office**: anyone walks into any room.
    Default-deny **locks every door**. Then you issue **specific keycards**: "frontend
    may enter gateway on port 8080", "orders may enter postgres on 5432". No keycard,
    no entry. An attacker who compromises `frontend` still can't reach the database.

### 21.2 Anatomy of an allow policy

![Policy anatomy](assets/diagrams/21-policy-anatomy.png)

A policy **selects target pods**, then whitelists **ingress sources** and **egress destinations** by label and port:

```yaml
# repo/manifests/60-security/network-policies.yaml (orders-allow section)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orders-allow
  namespace: tickethub
spec:
  podSelector:
    matchLabels: { app: orders }
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app: gateway } }   # only gateway may call orders
      ports:
        - { protocol: TCP, port: 8080 }
  egress:
    - to:                                                   # orders may reach payments
        - podSelector: { matchLabels: { app: payments } }
      ports: [{ protocol: TCP, port: 8080 }]
    - to:                                                   # and Postgres in data ns
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: data } }
          podSelector: { matchLabels: { app: postgres } }
      ports: [{ protocol: TCP, port: 5432 }]
    - to: []                                                # and DNS
      ports:
        - { protocol: UDP, port: 53 }
```

!!! warning "Forgetting egress DNS breaks everything subtly"
    Once you apply default-deny **egress**, pods can't resolve DNS — every service call
    fails with a lookup error, not a connection error, which is maddening to debug. Always
    include an egress allow for **UDP/TCP 53 to kube-dns**. This is the #1 NetworkPolicy
    gotcha.

### 21.3 Cilium's L7 superpower

Standard NetworkPolicy stops at L3/L4 (IP + port). **CiliumNetworkPolicy** goes to **L7** — allow only specific HTTP methods/paths, Kafka topics, or DNS names:

```yaml
# See: repo/manifests/ for the full manifest
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: { name: orders-l7, namespace: tickethub }
spec:
  endpointSelector: { matchLabels: { app: orders } }
  ingress:
    - fromEndpoints:
        - matchLabels: { app: gateway }
      toPorts:
        - ports: [{ port: "8080", protocol: TCP }]
          rules:
            http:                              # gateway may only GET/POST these paths
              - { method: "GET",  path: "/api/orders.*" }
              - { method: "POST", path: "/api/orders" }
```

!!! key "Segment by namespace, then by service"
    Coarse-grained first: block cross-namespace traffic except where required (apps →
    data on DB ports only). Then fine-grained within a namespace: service-to-service on
    exact ports. Cilium's L7 rules add a third layer — even an allowed caller can only hit
    the specific API it's supposed to. This is defense in depth for the network.


### 21.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **NetworkPolicy is additive — there is no `deny` rule, only the absence of an `allow`**: the default-deny policy (`podSelector: {}`, empty ingress and egress) drops everything. Each subsequent policy adds specific allows. Two policies that both select the same pod have their ingress/egress rules UNION-ed — you cannot use a later policy to undo an earlier allow.
    - **Cilium's `CiliumNetworkPolicy` supports L7 (HTTP/gRPC) rules, while the standard `NetworkPolicy` is L3/L4 only**: if you need to allow `POST /orders` but deny `DELETE /orders` from the same source, use `CiliumNetworkPolicy`. Standard `NetworkPolicy` cannot express HTTP method or path rules.
    - **`namespaceSelector` matches on namespace LABELS, not names**: `matchLabels: { kubernetes.io/metadata.name: tickethub }` works because Kubernetes auto-adds this label to namespaces (from v1.21+). For older clusters, you must add the label manually to the namespace, or the selector silently matches nothing.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Forgetting egress DNS (`port 53, kube-dns`)**: a default-deny egress policy that doesn't allow port 53 to the `kube-system` namespace breaks DNS resolution for the pod — causing connection failures that look like network policy blocks but are actually DNS failures. Always add a DNS egress allow to every namespace default-deny policy.
    - **Applying policy to DaemonSets before adding their egress rules**: if you apply default-deny to the `monitoring` namespace before adding egress rules for `node-exporter → Prometheus scrape`, the node-exporter pods become unreachable. Test policy in `warn` mode with Hubble flow observability before enforcing.
    - **Network Policy not supported by all CNIs**: Flannel + Calico combination, Weave, and some cloud CNIs have incomplete NetworkPolicy support. If you switch CNI, re-test all NetworkPolicy semantics. Cilium is fully compliant with the spec AND extends it — one of its key advantages.

!!! question "Architect Considerations"
    1. **Policy generation strategy**: writing NetworkPolicy by hand is error-prone. Use Hubble flow observability (Chapter 6) to observe actual traffic flows, then export them as policy drafts with `hubble observe --output policy`. Review and trim before applying — the generated policy is a starting point, not a final answer.
    2. **Namespace isolation boundary**: should the `data` namespace (Postgres, Kafka) be completely isolated from all namespaces except `tickethub`? Or should monitoring (Prometheus scrape) from `monitoring` ns also be allowed? Define the per-namespace trust model as a policy matrix before implementation.
    3. **Microservice-to-microservice policy granularity**: a single `allow tickethub → data port 5432` policy is simpler but allows any tickethub pod to reach Postgres. A tighter `allow orders-app → postgres port 5432` policy (using pod label selectors) limits blast radius if a less-privileged service is compromised.
    4. **Policy testing in CI**: add a `NetworkPolicy conformance test` to CI that deploys test pods and verifies that allowed connections succeed and denied connections are blocked. Tools like `cyclonus` or `netassert` automate this. Without automated tests, policy regressions are invisible.
    5. **Cilium FQDN policies for external egress**: Cilium supports `toFQDNs: [{matchName: "api.stripe.com"}]` to allow egress to specific external domains by DNS name — far more robust than IP-range-based egress rules (which break when Stripe rotates IPs). Use FQDN policies for all external API calls.

!!! success "Chapter 21 checklist"
    - **default-deny** ingress+egress in every app and data namespace.
    - Allow policies whitelist **only required** service-to-service flows by label + port.
    - **Egress DNS (53)** explicitly allowed everywhere.
    - Cross-namespace traffic (apps→data) restricted to DB ports only.
    - Sensitive paths tightened with **CiliumNetworkPolicy L7** rules.
    - Flows verified in **Hubble** (Chapter 6): `hubble observe --verdict DROPPED`.

---
