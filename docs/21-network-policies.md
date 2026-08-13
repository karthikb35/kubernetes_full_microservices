## <a name="ch21"></a>21. Network Policies — Zero-Trust Segmentation with Cilium

By default, **every pod in a Kubernetes cluster can talk to every other pod** — a flat, open network. For a platform handling payments that's unacceptable. **NetworkPolicies** turn the network zero-trust: deny everything, then allow only the flows TicketHub actually needs. Cilium (Chapter 6) enforces them in eBPF and extends them to L7.

### 21.1 The default-deny foundation

The first policy in every namespace denies all ingress and egress. From there you whitelist specific flows.

![Default deny](assets/diagrams/21-default-deny.png)

```yaml
# repo/manifests/60-security/default-deny.yaml
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
# repo/manifests/60-security/orders-netpol.yaml
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

!!! success "Chapter 21 checklist"
    - **default-deny** ingress+egress in every app and data namespace.
    - Allow policies whitelist **only required** service-to-service flows by label + port.
    - **Egress DNS (53)** explicitly allowed everywhere.
    - Cross-namespace traffic (apps→data) restricted to DB ports only.
    - Sensitive paths tightened with **CiliumNetworkPolicy L7** rules.
    - Flows verified in **Hubble** (Chapter 6): `hubble observe --verdict DROPPED`.

---
