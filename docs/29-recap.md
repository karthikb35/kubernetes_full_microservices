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


### 29.3 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **The request journey is not a straight line**: in the full sequence (User → CDN → Ingress → Gateway → Orders → Inventory → Payments → Kafka → Notifications), each hop involves DNS resolution, TLS handshake (potentially), TCP connection establishment, and application processing. Instruments show the TOTAL latency but each component in the chain can introduce jitter independently — distributed tracing (Tempo) is required to identify where p99 latency spikes originate.
    - **Kubernetes' asynchronous reconciliation means eventual consistency everywhere**: when you `kubectl apply` a Deployment change, the API server accepts it immediately, but the scheduler, kubelet, and container runtime each have their own reconcile cycle. The time from `apply` to all pods serving the new version can be 10-120 seconds depending on image pull time and readiness probe duration.
    - **The security model is defense in depth, not a single perimeter**: each layer (TLS, NetworkPolicy, RBAC, PSA, Kyverno, Falco) independently limits blast radius. An attacker who bypasses one layer still faces the others. The weakest link in the TicketHub security model is the shared `tickethub` namespace — services share namespace scope even though they have individual RBAC and NetworkPolicy.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **The mental model of "microservices are independent" breaks at the data layer**: Postgres, Kafka, and Redis are shared infrastructure. A Postgres volume fill, a Kafka partition leadership election storm, or a Redis BGSAVE blocking event affects ALL services that depend on them — regardless of pod isolation. Monitor data-layer SLIs as aggressively as application-layer SLIs.
    - **GitOps and human-made kubectl changes create invisible drift**: an operator who directly edits a running ConfigMap bypasses git, creating state that Argo CD will revert on next sync. Establish a cultural and tooling norm: `kubectl edit` is a debugging tool, not a change management tool. All persistent changes go through git.
    - **Observability requires active maintenance**: Prometheus alerts go stale (metric names change after service refactors), Grafana dashboards drift from reality, and Loki label schemes accumulate technical debt. Schedule a quarterly observability review: which alerts fired in the last quarter? Which were false positives? Which incidents had no alert?

!!! question "Architect Considerations"
    1. **Total Cost of Ownership (TCO) review**: after building the full cluster, calculate the operational overhead: how many engineer-hours per week does cluster maintenance consume? How does this compare to managed Kubernetes (EKS, GKE)? On-prem gives control and lower cloud cost at the expense of operational burden — re-validate this trade-off annually.
    2. **Runbook completeness audit**: for every chapter in this book, there is a corresponding operational scenario. Does a runbook exist for: Postgres primary failover? Kafka broker crash? etcd member failure? Node OOM eviction cascade? Certificate near-expiry alert response? Runbook completeness is a direct measure of operational readiness.
    3. **Chaos engineering readiness**: before declaring the cluster production-ready, run controlled chaos experiments: kill a control-plane node (does etcd recover?), kill the primary Postgres pod (does the operator promote a standby?), saturate a data node's disk (does the alert fire before Ceph goes critical?). Use Chaos Mesh or LitmusChaos to automate these experiments.
    4. **Graduation path**: this textbook builds a single on-prem cluster. Real production platforms grow: second cluster for DR, multi-region, multi-tenancy. Review the design choices that would need to change at each scale step: CNI (Cluster Mesh), storage (multi-site Ceph), gitops (multi-cluster ApplicationSet), RBAC (federated identity).
    5. **Documentation as living infrastructure**: the `docs/` in this repository are the authoritative reference for how the cluster was built and why each decision was made. Treat architecture decision records (ADRs) with the same rigor as code: every major design decision has a corresponding ADR document committed to the repository.

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
