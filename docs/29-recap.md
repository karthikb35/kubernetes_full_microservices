## <a name="ch29"></a>29. End-to-End Recap — A Request's Full Journey

We began with bare-metal servers in a data center and ended with a secured, observable, GitOps-delivered microservices platform. This final chapter ties all 28 preceding chapters together by following **one user request** — buying a concert ticket — through every layer we built, and then stepping back to see the whole stack at once.

### 29.1 One ticket purchase, every layer

![Request journey](assets/diagrams/29-request-journey.png)

Trace a single `POST /api/orders` from tap to confirmation:

1. **DNS → MetalLB** (Ch 7) — the domain resolves to a `LoadBalancer` IP that MetalLB advertises from bare metal, with no cloud provider.
2. **NGINX Ingress + TLS** (Ch 7) — terminates HTTPS with a cert-manager certificate and routes `/api` by host/path rule.
3. **NetworkPolicy check** (Ch 21) — Cilium's eBPF datapath confirms the ingress is *allowed* to reach the gateway; every other path is denied by default.
4. **gateway pod** (Ch 11, 12) — a Deployment behind a ClusterIP Service, running as a **non-root, restricted** pod (Ch 20) under a **least-privilege ServiceAccount** (Ch 19).
5. **orders pod** (Ch 12, 16) — reached by DNS service discovery; **HPA** has scaled it out for the on-sale surge, load-balanced by Cilium eBPF (Ch 6).
6. **payments pod** (Ch 17) — a **PriorityClass**-critical service that survives node pressure and preempts batch work.
7. **postgres-0** (Ch 8, 14) — a **StatefulSet** pod with a stable identity and a **Ceph-backed PV**, reachable only on port 5432 per NetworkPolicy.
8. **Kafka event** (Ch 16) — orders publishes `ticket-purchased`; **KEDA** scales the notifications consumer on queue lag to email the ticket.
9. **Observed, watched, delivered** (Ch 23, 26, 28) — the whole flow emits **metrics/logs/traces** (Prometheus/Loki/Hubble), is **watched at runtime** by Falco, and every component was **delivered by Argo CD** from Git.

!!! key "No single feature ships a ticket — the system does"
    The purchase succeeds because *every* layer cooperates: the network lets exactly the
    right pods talk, autoscaling gives them capacity, scheduling keeps the critical ones
    alive, storage persists the order, security fences the whole thing, and observability
    proves it worked. Architecture is the discipline of making these layers **compose**.

### 29.2 The complete stack, bottom to top

![Full stack](assets/diagrams/29-full-stack.png)

| Part | Layer | Chapters |
|------|-------|----------|
| I | Physical & architecture design (bare metal → VMs → topology → network) | 1–4 |
| II | Cluster install & core platform (kubeadm, Cilium, MetalLB, Ceph, namespaces) | 5–9 |
| III | Building & deploying services (Dockerfiles, controllers, Services, config, storage) | 10–14 |
| IV | Reliability, scaling & scheduling (resources, autoscaling, placement, health) | 15–18 |
| V | Security & governance (RBAC, PSA, NetPol, Kyverno, Falco, supply chain, CRDs) | 19–25 |
| VI | Observability & operations (monitoring, backup/DR, GitOps) | 26–28 |

### 29.3 The architect's enduring principles

!!! success "The ten principles this book was built on"
    1. **Design failure domains first** — VMs, node pools, and quorum before workloads (Ch 2–3).
    2. **Everything declarative, in Git** — the cluster is reproducible, not hand-crafted (Ch 28).
    3. **Bootstrap order is sacred** — CNI → storage → policy → data → apps (Ch 9).
    4. **Right-size, then autoscale** — accurate requests make QoS and HPA honest (Ch 15–16).
    5. **Redundancy only counts if it's spread** — anti-affinity + PDB + topology spread (Ch 17).
    6. **Zero-trust by default** — deny-all network and least-privilege RBAC, then allow (Ch 19, 21).
    7. **Harden the pod and the supply chain** — non-root, signed images, encrypted secrets (Ch 20, 24).
    8. **Detect what you can't prevent** — Falco watches runtime; alerts fire on SLOs (Ch 23, 26).
    9. **Practice failure** — backups you restore, upgrades you rehearse (Ch 27).
    10. **Automate the operational knowledge** — operators and GitOps, not tribal memory (Ch 25, 28).

### 29.4 Where to go next

TicketHub is a complete foundation. Natural extensions: a **service mesh** (Istio/Cilium Service Mesh) for mTLS and fine traffic control; **multi-cluster** federation for regional HA; **cost governance** (Kubecost); **FinOps-aware autoscaling**; and **progressive delivery** maturity with automated canary analysis. Each builds on — and reuses — the primitives in this book.

!!! key "You are now the architect"
    Every concept — pods to operators, CIDRs to sync waves — now connects to a real
    decision you can defend: *why this node pool, why this StorageClass, why this
    NetworkPolicy, why this sync wave.* That web of justified decisions, from the bare metal
    up, **is** cluster architecture. TicketHub was the vehicle; the judgment is yours to reuse.

---

*End of book — "Designing, Installing & Operating a Production Kubernetes Cluster." The companion `repo/` contains every Dockerfile and manifest referenced across these 29 chapters, organized by bootstrap order for `kubectl apply` or Argo CD sync.*
