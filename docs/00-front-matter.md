# Designing, Installing & Operating a Production Kubernetes Cluster

### A Cluster Architect's Textbook — built around **TicketHub**, a real-world event-ticketing microservices platform

**Author's role:** You are the **Kubernetes Cluster Architect** for TicketHub. This book walks the entire journey — from **bare-metal servers** in a data center, through **VM slicing**, **cluster installation**, **platform services**, **containerizing 9 microservices**, and every workload, scaling, scheduling, security, and observability concern a production cluster needs.

**Assumed knowledge:** none beyond basic Linux and "what a container is". Every concept is introduced from first principles, then applied to TicketHub with **real diagrams, Dockerfiles, and YAML** you can run from the companion `repo/`. If any term feels assumed, start with the **[Chapter 0 primer](00b-prerequisites.md)** and the **[Glossary](30-appendix-glossary.md)** — they define the recurring vocabulary (the object model, kubectl, Helm, CIDR, Kafka/Redis) so no later chapter has to stop and explain it.

**Platform decisions (fixed for the whole book):**

| Layer | Choice |
|-------|--------|
| Virtualization | KVM / libvirt (Proxmox) on bare metal |
| Kubernetes install | `kubeadm` (vanilla upstream), HA control plane |
| CNI | **Cilium** (eBPF) + **Hubble** observability |
| Load balancer | **MetalLB** (bare-metal `LoadBalancer` services) |
| Ingress | **NGINX Ingress Controller** |
| Storage | **Rook-Ceph** (block, file, S3 object) |
| Policy / security | Pod Security Admission, **Kyverno**, **Falco**, RBAC, NetworkPolicy |
| Autoscaling | Metrics Server, **HPA**, **VPA**, Cluster Autoscaler, **KEDA** |
| Delivery | **Argo CD** (GitOps) |
| DB Replication | Custom CRDs (`PostgresReplicationCluster`, `ReplicationSlot`) |

---

## Table of Contents

### Front Matter
0. [Prerequisites & a Five-Minute Primer](00b-prerequisites.md)

### Part I — Physical & Architecture Design
1. [The TicketHub Scenario — Services, Interfaces & Interactions](01-scenario.md)
2. [From Bare Metal to Virtual Machines](02-baremetal-to-vm.md)
3. [Cluster Topology — Control Plane & Worker Node Design](03-topology.md)
4. [Network Design — Subnets, CIDRs, North-South & East-West](04-network-design.md)

### Part II — Cluster Installation & Core Platform
5. [Installing Kubernetes with kubeadm (HA control plane)](05-kubeadm-install.md)
6. [The CNI: Cilium (eBPF) + Hubble](06-cilium-cni.md)
7. [Load Balancing & Ingress: MetalLB + NGINX](07-metallb-ingress.md)
7A. [Certificate & PKI Management — cluster PKI + application mTLS](07b-certificates.md)
8. [Storage: Rook-Ceph, StorageClasses, dynamic PV/PVC](08-storage-rook-ceph.md)
9. [Namespaces, the Resource Model & Bootstrap Ordering](09-namespaces-resources.md)

### Part III — Building & Deploying the Services
10. [Containerizing the Services — Dockerfiles (multi-stage, distroless, non-root)](10-containerizing.md)
11. [Workload Controllers — Deployments, ReplicaSets, StatefulSets, DaemonSets](11-workload-controllers.md)
12. [Services & Traffic — ClusterIP, headless, Ingress routing](12-services-traffic.md)
13. [Configuration & Secrets — ConfigMaps, Secrets, External Secrets](13-config-secrets.md)
14. [Stateful Storage — PV/PVC, StatefulSet volumeClaimTemplates + DB Replication CRDs](14-stateful-storage.md)

### Part IV — Reliability, Scaling & Scheduling
15. [Resource Management — requests/limits, QoS, LimitRange, ResourceQuota](15-resource-management.md)
16. [Autoscaling — Metrics Server, HPA, VPA, Cluster Autoscaler, KEDA](16-autoscaling.md)
17. [Scheduling & Placement — PriorityClass, affinity, taints/tolerations, topology spread, PDB](17-scheduling-placement.md)
18. [Health & Lifecycle — probes, rollout strategies, graceful shutdown](18-health-lifecycle.md)

### Part V — Security & Governance
19. [RBAC & Service Accounts — least privilege per service](19-rbac.md)
20. [Pod Security Admission & SecurityContext Hardening](20-pod-security.md)
21. [Network Policies — zero-trust segmentation with Cilium](21-network-policies.md)
22. [Policy as Code — Kyverno (validate / mutate / generate)](22-kyverno.md)
23. [Runtime Threat Detection — Falco](23-falco.md)
24. [Secrets at Rest, Image Signing & Supply-Chain Security](24-secrets-supply-chain.md)
25. [Extending Kubernetes — CRDs & Operators (incl. DB Replication CRDs)](25-crds-operators.md)

### Part VI — Observability & Operations
26. [Observability — Prometheus, Grafana, Loki, Hubble](26-observability.md)
27. [Backup, DR, Upgrades & Node Maintenance](27-backup-dr-upgrades.md)
28. [GitOps Delivery with Argo CD](28-gitops-argocd.md)
29. [End-to-End Recap — a Request's Full Journey](29-recap.md)

### Appendices
A. [Glossary](30-appendix-glossary.md)

---

!!! note "How this book is organized"
    Each chapter follows the same rhythm: **concept from basics → a color-coded
    diagram → the TicketHub application → real YAML/commands → an architect's
    checklist**. The six parts build strictly on one another — from bare-metal
    physical design, through cluster installation and service deployment, to
    reliability, security, and day-2 operations. Every Dockerfile and manifest
    referenced lives in the companion `repo/`, organized by bootstrap order.

!!! key "The TicketHub platform at a glance"
    9 microservices — **Frontend UI, API Gateway, Users/Auth, Catalog, Inventory,
    Orders, Payments, Notifications, Search** — backed by **PostgreSQL, Redis,
    Kafka, and a Ceph object store**, running on a **12-node** cluster (3 control
    plane + 9 workers across general / data / infra pools).
