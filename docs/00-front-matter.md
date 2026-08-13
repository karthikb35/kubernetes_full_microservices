# Designing, Installing & Operating a Production Kubernetes Cluster

### A Cluster Architect's Textbook — built around **TicketHub**, a real-world event-ticketing microservices platform

**Author's role:** You are the **Kubernetes Cluster Architect** for TicketHub. This book walks the entire journey — from **bare-metal servers** in a data center, through **VM slicing**, **cluster installation**, **platform services**, **containerizing 9 microservices**, and every workload, scaling, scheduling, security, and observability concern a production cluster needs.

**Assumed knowledge:** none beyond basic Linux and "what a container is". Every concept is introduced from first principles, then applied to TicketHub with **real diagrams, Dockerfiles, and YAML** you can run from the companion `repo/`. If any term feels assumed, start with the **[Chapter 0 primer](#ch0)** and the **[Glossary](#appendix-a)** — they define the recurring vocabulary (the object model, kubectl, Helm, CIDR, Kafka/Redis) so no later chapter has to stop and explain it.

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

---

## Table of Contents

### Front Matter
0. [Prerequisites & a Five-Minute Primer](#ch0)

### Part I — Physical & Architecture Design
1. [The TicketHub Scenario — Services, Interfaces & Interactions](#ch1)
2. [From Bare Metal to Virtual Machines](#ch2)
3. [Cluster Topology — Control Plane & Worker Node Design](#ch3)
4. [Network Design — Subnets, CIDRs, North-South & East-West](#ch4)

### Part II — Cluster Installation & Core Platform
5. [Installing Kubernetes with kubeadm (HA control plane)](#ch5)
6. [The CNI: Cilium (eBPF) + Hubble](#ch6)
7. [Load Balancing & Ingress: MetalLB + NGINX](#ch7)
7A. [Certificate & PKI Management — cluster PKI + application mTLS](#ch7a)
8. [Storage: Rook-Ceph, StorageClasses, dynamic PV/PVC](#ch8)
9. [Namespaces, the Resource Model & Bootstrap Ordering](#ch9)

### Part III — Building & Deploying the Services
10. [Containerizing the Services — Dockerfiles (multi-stage, distroless, non-root)](#ch10)
11. [Workload Controllers — Deployments, ReplicaSets, StatefulSets, DaemonSets](#ch11)
12. [Services & Traffic — ClusterIP, headless, Ingress routing](#ch12)
13. [Configuration & Secrets — ConfigMaps, Secrets, External Secrets](#ch13)
14. [Stateful Storage — PV/PVC, StatefulSet volumeClaimTemplates](#ch14)

### Part IV — Reliability, Scaling & Scheduling
15. [Resource Management — requests/limits, QoS, LimitRange, ResourceQuota](#ch15)
16. [Autoscaling — Metrics Server, HPA, VPA, Cluster Autoscaler, KEDA](#ch16)
17. [Scheduling & Placement — PriorityClass, affinity, taints/tolerations, topology spread, PDB](#ch17)
18. [Health & Lifecycle — probes, rollout strategies, graceful shutdown](#ch18)

### Part V — Security & Governance
19. [RBAC & Service Accounts — least privilege per service](#ch19)
20. [Pod Security Admission & SecurityContext Hardening](#ch20)
21. [Network Policies — zero-trust segmentation with Cilium](#ch21)
22. [Policy as Code — Kyverno (validate / mutate / generate)](#ch22)
23. [Runtime Threat Detection — Falco](#ch23)
24. [Secrets at Rest, Image Signing & Supply-Chain Security](#ch24)
25. [Extending Kubernetes — CRDs & Operators](#ch25)

### Part VI — Observability & Operations
26. [Observability — Prometheus, Grafana, Loki, Hubble](#ch26)
27. [Backup, DR, Upgrades & Node Maintenance](#ch27)
28. [GitOps Delivery with Argo CD](#ch28)
29. [End-to-End Recap — a Request's Full Journey](#ch29)

### Appendices
A. [Glossary](#appendix-a)

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
