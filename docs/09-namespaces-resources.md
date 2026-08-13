## <a name="ch9"></a>9. Namespaces, the Resource Model & Bootstrap Ordering

The cluster now has networking and storage. Before we deploy a single application pod, an architect defines the **organizational structure** — namespaces — and the **order** in which everything must come up. Get this wrong and you get tangled dependencies, noisy-neighbor problems, and security gaps.

### 9.1 Namespaces — the unit of isolation

A **namespace** is a virtual cluster inside the cluster. It's the boundary for **RBAC**, **ResourceQuota**, **NetworkPolicy**, and **Pod Security Admission** — nearly every governance control is applied per namespace.

![TicketHub namespace layout](assets/diagrams/09-namespaces.png)

| Namespace | Contents | Why separate |
|-----------|----------|--------------|
| `tickethub` | The 9 application services | The product; app-team RBAC |
| `data` | Postgres, Redis, Kafka | Stateful; stricter policy, data-team RBAC |
| `platform` | Ingress, MetalLB, cert-manager | Shared infra; platform-team only |
| `rook-ceph` | Storage operator + Ceph | Isolated blast radius |
| `monitoring` | Prometheus, Grafana, Loki | Cross-cutting; read access clusterwide |
| `security` | Falco, Kyverno | Enforcement plane, tightly locked |
| `argocd` | GitOps controller | Deploys everything else |

!!! mental "Mental model — departments in a company"
    Namespaces are **departments**. Each has its own budget (**ResourceQuota**), its own
    staff access (**RBAC**), its own security rules (**PSA/NetworkPolicy**), and its own
    door policy (who may talk to whom). You wouldn't give the summer intern keys to the
    finance vault — likewise the app team doesn't get write access to `rook-ceph`.

```yaml
# repo/manifests/00-namespaces/namespaces.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tickethub
  labels:
    team: app
    pod-security.kubernetes.io/enforce: restricted   # PSA from day one (Ch 20)
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: data
  labels:
    team: data
    pod-security.kubernetes.io/enforce: baseline      # DBs may need slightly more
```

!!! tip "Apply Pod Security labels at namespace creation"
    Bake the `pod-security.kubernetes.io/enforce` label into the namespace definition
    from the start (Chapter 20). Adding it later to a namespace full of running,
    non-compliant workloads is a painful retrofit.

### 9.2 The resource model — how requests/limits nest

Understanding the **nesting** of resources is essential before deploying workloads (deep dive in Chapter 15):

![Resource model nesting](assets/diagrams/09-resource-model.png)

- **Container** declares `requests` (guaranteed) and `limits` (ceiling) for CPU/memory.
- **Pod** resources = the sum of its containers'.
- **Namespace** caps the total via **ResourceQuota**, and sets per-container defaults via **LimitRange**.
- The **scheduler** places pods by comparing **requests** to each node's **allocatable** capacity.

```yaml
# repo/manifests/00-namespaces/quota-tickethub.yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: tickethub-quota, namespace: tickethub }
spec:
  hard:
    requests.cpu: "40"
    requests.memory: 80Gi
    limits.cpu: "80"
    limits.memory: 160Gi
    pods: "200"
    persistentvolumeclaims: "50"
---
apiVersion: v1
kind: LimitRange           # default requests/limits so pods can't be "unbounded"
metadata: { name: tickethub-defaults, namespace: tickethub }
spec:
  limits:
    - type: Container
      default:        { cpu: "500m", memory: 512Mi }
      defaultRequest: { cpu: "100m", memory: 128Mi }
```

!!! warning "A namespace without a ResourceQuota is a runaway risk"
    Without a quota, one buggy Deployment scaling to hundreds of pods can starve the
    whole cluster. A LimitRange also prevents pods that specify **no** requests (which
    the scheduler treats as near-zero, packing nodes dangerously). Set both on every
    app namespace.

### 9.3 Bootstrap ordering — dependencies flow one way

Platform components have a strict dependency order. Installing them out of order causes pods stuck `Pending` (no CNI), PVCs stuck unbound (no storage), or Services with no external IP (no MetalLB).

![Bootstrap order](assets/diagrams/09-bootstrap-order.png)

| # | Layer | Depends on | Why |
|---|-------|-----------|-----|
| 1 | Cluster (kubeadm) | — | The foundation |
| 2 | **CNI (Cilium)** | 1 | **Nothing schedules** without pod networking |
| 3 | Storage (Rook-Ceph) + SCs | 2 | Stateful things need PVs |
| 4 | LB + Ingress (MetalLB, NGINX) | 2 | External access |
| 5 | Platform (cert-manager, ESO) | 3,4 | TLS, secrets |
| 6 | Security/policy (PSA, Kyverno, Falco) | 1 | Enforce **before** apps land |
| 7 | Observability | 3 | Persist metrics/logs |
| 8 | Stateful data (Postgres, Kafka, Redis) | 3 | Needs storage |
| 9 | **App services** | all | Come **last** |

!!! key "Two ordering rules that prevent most bootstrap pain"
    1. **CNI before anything** — until a CNI is up, every pod is `Pending`.
    2. **Policy before apps** — install PSA/Kyverno/Falco *before* workloads, so the
       first app pod is already governed. Retrofitting policy onto running apps means
       discovering violations in production.

### 9.4 Making bootstrap reproducible

An architect never clicks through this by hand. The ordering is encoded as **Argo CD sync waves** (Chapter 28) or a Helmfile, so the entire platform reconstructs itself deterministically:

```yaml
# Argo CD sync-wave annotation encodes the order declaratively
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "2"    # Cilium in wave 2, apps in wave 9
```

!!! success "Chapter 9 checklist — Part II complete"
    - **Namespaces** created with team labels + **PSA** labels from day one.
    - **ResourceQuota + LimitRange** on every app namespace.
    - The **bootstrap order** understood and encoded (CNI → storage/LB → policy → data → apps).
    - Platform install made **reproducible** (GitOps sync waves).

    The platform is now ready. **Part III** containerizes the 9 TicketHub services and
    deploys them with the right workload controllers.

---
