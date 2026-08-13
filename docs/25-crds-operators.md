## <a name="ch25"></a>25. Extending Kubernetes — CRDs & Operators

Almost every platform component in this book — Cilium, Rook-Ceph, MetalLB, cert-manager, Kyverno, Prometheus — is installed by defining **custom resources** that Kubernetes doesn't ship with. That's not a coincidence: it's the **operator pattern**, the way Kubernetes is meant to be extended. This chapter closes Part V by explaining the machinery you've been using all along.

### 25.1 CustomResourceDefinitions — teaching the API new nouns

A **CRD** registers a new resource *kind* with the API server. After applying a CRD, `kubectl get postgresclusters` works as if it were built in — same RBAC, same `kubectl`, same declarative YAML.

![CRD and operator](assets/diagrams/25-crd-operator.png)

| Native | Custom (via CRD) |
|--------|------------------|
| `kind: Deployment` | `kind: CephCluster` |
| `kind: Service` | `kind: CiliumNetworkPolicy` |
| `kind: Secret` | `kind: ClusterPolicy` (Kyverno) |

```yaml
# a CRD (abbreviated) — this is what an operator ships
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: { name: postgresclusters.tickethub.io }
spec:
  group: tickethub.io
  names: { kind: PostgresCluster, plural: postgresclusters }
  scope: Namespaced
  versions:
    - name: v1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                replicas: { type: integer }
                version:  { type: string }
```

### 25.2 The operator — a controller with domain knowledge

A CRD by itself is inert — just a new noun in the database. The **operator** is the **controller** that gives it behavior: it watches those custom resources and drives the real world to match, using the same **reconcile loop** Kubernetes uses internally.

![Operator pattern](assets/diagrams/25-operator-pattern.png)

```text
loop forever:
    observe  = read desired state (the CR) + actual state (real objects)
    diff     = compute the difference
    act      = create / update / delete to converge
```

!!! mental "Mental model — hiring an expert DBA who never sleeps"
    Running Postgres HA by hand needs a **DBA**: provision disks, configure replication,
    fail over the primary, take backups. An **operator encodes that DBA's knowledge as
    software**. You declare `kind: PostgresCluster, replicas: 3`; the operator does
    everything a human DBA would — continuously, at 3am, without a ticket. The CRD is the
    *request form*; the operator is the *tireless expert* fulfilling it.

### 25.3 Why this matters for TicketHub

You've relied on operators throughout the build:

| Custom resource | Operator | What it automates |
|-----------------|----------|-------------------|
| `CephCluster` | Rook | Provisions/heals Ceph (Ch 8) |
| `CiliumNetworkPolicy` | Cilium | eBPF network enforcement (Ch 6, 21) |
| `IPAddressPool` | MetalLB | Bare-metal LoadBalancer IPs (Ch 7) |
| `Certificate` | cert-manager | Issues/renews TLS (Ch 7) |
| `ClusterPolicy` | Kyverno | Admission policy (Ch 22) |
| `ScaledObject` | KEDA | Event-driven scaling (Ch 16) |

!!! key "Prefer a mature operator over hand-rolled YAML for stateful systems"
    You *could* run Postgres with a raw StatefulSet (Chapter 14) — but failover, backups,
    and version upgrades are then your problem. A battle-tested operator (CloudNativePG,
    Strimzi for Kafka) encodes years of operational hard-won lessons. For complex stateful
    software, adopt the operator; reserve hand-written manifests for your own stateless apps.

### 25.4 When to write your own

Most teams **consume** operators; occasionally you **build** one — to encode *your* domain, e.g. a `TicketHubTenant` CRD that provisions a namespace, quota, network policies, and per-tenant databases in one declarative object. Frameworks like **Kubebuilder** and the **Operator SDK** scaffold the controller so you write only the reconcile logic.

!!! warning "An operator is a privileged controller — scope it tightly"
    Operators typically hold broad RBAC (they create Deployments, Secrets, PVCs). A
    compromised or buggy operator is high-blast-radius. Install operators from trusted
    sources, pin versions, review their RBAC, and give each the **narrowest** ClusterRole
    that lets it do its job (Chapter 19).

!!! success "Chapter 25 checklist — Part V complete"
    - Understand CRDs (**new API nouns**) + operators (**controllers that reconcile them**).
    - Stateful systems (DB, Kafka, Ceph) run via **mature operators**, not hand-rolled YAML.
    - Operator RBAC reviewed and **scoped tightly**; versions pinned; sources trusted.
    - Custom operators (if any) scaffolded with Kubebuilder/Operator SDK.

    TicketHub is now **secured end to end**: identity (RBAC), the pod (PSA/SecurityContext),
    the network (NetworkPolicy), policy (Kyverno), runtime (Falco), and the supply chain
    (encryption + signing). **Part VI** operates it: observability, backup/DR, upgrades,
    and GitOps delivery.

---
