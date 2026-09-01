## <a name="appendix-a"></a>Appendix A — Glossary

A quick-reference for the vocabulary used throughout this book. Terms are alphabetical;
the **Ch** column points to where the concept is developed in depth. For the foundational
five (object model, kubectl, Helm, CIDR, the stateful backends) see the **[Chapter 0
primer](00b-prerequisites.md)**.

| Term | Definition | Ch |
|------|------------|----|
| **ACID** | Atomicity, Consistency, Isolation, Durability — the guarantees a single database transaction gives. Across *separate* microservice databases these don't hold, which is why we use the **Saga** pattern instead. | 1 |
| **Admission** | The third gate in the API server (after authN/authZ): validates or mutates an object before it is stored. Home of **PSA** and **Kyverno**. | 0, 20, 22 |
| **Affinity / anti-affinity** | Scheduling rules that *attract* pods to nodes/labels (affinity) or keep replicas *apart* (anti-affinity) for resilience. | 17 |
| **ARP** | Address Resolution Protocol — how a machine on a LAN maps an IP to a hardware (MAC) address. MetalLB **L2 mode** answers ARP to claim an external IP. | 4, 7 |
| **AuthN / AuthZ** | Authentication (*who are you?* — cert/OIDC) vs Authorization (*are you allowed?* — RBAC). Two distinct API-server gates. | 0, 19 |
| **BGP** | Border Gateway Protocol — how routers exchange routes. MetalLB **BGP mode** peers with your router to load-share an external IP across nodes (vs single-node L2). | 4, 7 |
| **CA (Certificate Authority)** | The trusted signer of certificates. `kubeadm` creates a **cluster CA** that signs an identity for every component and node (the cluster's **PKI**). The full inventory, HA SANs, and renewal are in Chapter 7A. | 5, 7A |
| **cgroup / cgroup driver** | Linux control groups limit/account a process's CPU & memory (how requests/limits are enforced). The *driver* (`systemd` vs `cgroupfs`) must match between containerd and kubelet. | 0, 5, 15 |
| **CIDR** | `IP/prefixlen` notation (e.g. `10.244.0.0/16`). The `/N` fixes the leading N bits as the network; smaller N = larger range. Cluster CIDRs must never overlap. | 0, 4 |
| **ClusterIP** | The default Service type: a stable virtual IP + DNS name reachable **only inside** the cluster. | 12 |
| **CNI** | Container Network Interface — the plugin that gives pods IPs and wires their networking. We use **Cilium**. | 6 |
| **Compensating transaction** | An action that *undoes* a completed step when a later step in a **Saga** fails (e.g. `ReleaseSeats()` after a failed payment). | 1 |
| **CRD / Operator** | A CustomResourceDefinition teaches the API a new *kind*; an **operator** is the controller that reconciles it — the standard way to extend Kubernetes. | 25 |
| **CRI** | Container Runtime Interface — the API kubelet uses to run containers via a runtime like **containerd**. | 5 |
| **CSI** | Container Storage Interface — the standard plugin API that lets Kubernetes provision storage from any backend (Ceph RBD, cloud disks). The Rook StorageClass `provisioner` is a CSI driver. | 8, 14 |
| **DaemonSet** | A controller that runs exactly one pod **per node** (CNI agent, node-exporter, Falco). | 11 |
| **Deployment / ReplicaSet** | A Deployment manages ReplicaSets, which manage N interchangeable stateless pod replicas with rolling updates + rollback. | 11 |
| **DSR (Direct Server Return)** | A load-balancing mode where the reply skips the load balancer and returns straight to the client — lower latency. Cilium option. | 6 |
| **eBPF** | Small sandboxed programs loaded into the Linux kernel. Cilium uses eBPF for routing, service load-balancing, and policy — far faster than iptables at scale. | 4, 6 |
| **EndpointSlice** | The auto-maintained list of **Ready** pod IPs behind a Service; readiness probes gate membership. | 12 |
| **etcd** | The cluster's key/value database holding all state. Consensus via **Raft**; needs an odd quorum (3 or 5). | 3, 5 |
| **front-proxy CA** | A separate CA that signs the aggregation-layer client cert, isolating extension/aggregated API servers from the main cluster CA. | 7A |
| **gRPC** | A fast, strongly-typed, binary RPC protocol (HTTP/2) for **service-to-service** calls. TicketHub uses gRPC internally and REST/JSON at the edge. | 1, 12 |
| **Headless Service** | A Service with `clusterIP: None` that returns individual pod IPs and gives StatefulSet pods stable per-pod DNS (`postgres-0.postgres…`). | 12, 14 |
| **Helm** | The Kubernetes package manager: a **chart** (templated YAML) + your **values** → an installed **release**. | 0 |
| **hostNetwork** | A pod setting that puts the pod on the *node's* network namespace (bypassing the Pod CIDR). Used sparingly (e.g. ingress). | 4 |
| **HPA / VPA / KEDA / Cluster Autoscaler** | Autoscalers for, respectively: replica **count**, per-pod **size**, **event-driven** replicas, and **node** count. | 16 |
| **IPAM** | IP Address Management — how the CNI hands out pod IPs from the Pod CIDR. | 6 |
| **JWT** | JSON Web Token — a signed, self-contained token proving a user's identity/claims. The Users/Auth service issues them; the gateway verifies them. | 1 |
| **keepalived / VRRP** | keepalived uses the VRRP protocol to float a **virtual IP** between nodes, so the API endpoint stays reachable if one load-balancer node dies. | 3 |
| **kube-proxy** | The classic component that programs `iptables`/IPVS rules to route Service traffic to pods. Cilium **replaces** it with eBPF for speed and simplicity. | 4, 6 |
| **LimitRange / ResourceQuota** | Per-namespace guardrails: LimitRange sets default/min/max per container; ResourceQuota caps the namespace total. | 9, 15 |
| **mTLS (mutual TLS)** | Both sides of a connection present and validate certificates, so client *and* server prove identity. Every control-plane link is mTLS; east-west service mTLS is added via an internal CA or a mesh. | 7A |
| **NetworkPolicy** | Firewall rules for pod traffic by label/port. Default-deny then allow; Cilium extends to L7. | 21 |
| **NDP** | Neighbor Discovery Protocol — the IPv6 equivalent of ARP; MetalLB L2 uses it for IPv6. | 4 |
| **OIDC** | OpenID Connect — the token-based protocol external identity providers (Okta, Entra ID) use to authenticate *humans* to the API server. | 0, 19 |
| **OSD / mon / mgr** | Ceph daemons: OSD stores data (one per disk), mon keeps the cluster map + quorum, mgr does metrics/orchestration. | 8 |
| **PDB (PodDisruptionBudget)** | Guarantees a minimum number of a service's pods stay up during *voluntary* disruptions (node drains, upgrades). | 17, 27 |
| **Percentile (P50 / P95 / P99)** | The value below which that % of samples fall. P99 latency = "99% of requests are faster than this." Size memory limits near P99; requests near P50–P75. | 15 |
| **PKI** | Public Key Infrastructure — the system of a CA plus the certificates it signs. The cluster runs its own; see Chapter 7A for the full hierarchy and lifecycle. | 5, 7A |
| **PV / PVC / StorageClass** | A PVC *requests* storage, a StorageClass describes *how* to provision it, and a PV is the *actual* volume created. | 8, 14 |
| **QoS class** | Guaranteed / Burstable / BestEffort — derived from requests vs limits; decides eviction order under memory pressure. | 15 |
| **Quorum** | The majority of members a consensus system needs to agree (2 of 3, 3 of 5). Below quorum, etcd stops accepting writes. | 3 |
| **Raft** | The consensus protocol etcd uses to keep replicas in agreement via an elected leader + majority quorum. | 3 |
| **RBAC** | Role-Based Access Control — grants *verbs on resources* to subjects (users/groups/ServiceAccounts). Additive, default-deny. | 19 |
| **RED / USE** | Alerting methods: RED = Rate, Errors, Duration (for services); USE = Utilization, Saturation, Errors (for resources). | 26 |
| **Reconcile loop** | The observe → diff → act cycle every controller/operator runs to drive actual state toward desired state. | 0, 25 |
| **REST** | A resource-oriented HTTP/JSON API style, browser-friendly; used at TicketHub's edge (vs gRPC internally). | 1 |
| **Saga** | A pattern for multi-step transactions across microservices: a sequence of local commits, each with a **compensating** undo if a later step fails. | 1 |
| **SAN / certSANs** | Subject Alternative Names — the list of DNS names/IPs a certificate is valid for. `apiServer.certSANs` must include the HA **VIP** or calls through the load balancer fail TLS. | 7A |
| **SBOM / SLSA** | A Software Bill of Materials lists an image's components; SLSA provenance attests *how* it was built — both speed up CVE response. | 24 |
| **seccomp** | A Linux kernel filter restricting which syscalls a process may make; `RuntimeDefault` blocks dangerous ones. | 20 |
| **ServiceAccount** | The identity a **pod** uses to call the API server. Give each workload its own, least-privilege one. | 19 |
| **SPIFFE** | A standard for cryptographic **workload identity** (a SPIFFE ID per workload). Service meshes issue and auto-rotate SPIFFE identities to do transparent mTLS. | 7A |
| **StatefulSet** | A controller for stateful pods: stable ordinal identity (`postgres-0`) + one persistent volume per replica, ordered operations. | 11, 14 |
| **Static pod** | A pod the kubelet runs directly from a node file (not the API). The control-plane components run this way. | 0, 5 |
| **Taint / Toleration** | A taint *repels* pods from a node; only pods that *tolerate* it may land. Pairs with labels to build dedicated node pools. | 3, 17 |
| **trust-manager** | A cert-manager companion that publishes a CA bundle as a ConfigMap into every namespace, so workloads can trust an internal CA without manual copying. | 7A |
| **veth pair** | A virtual cable with one end in a pod's network namespace and one on the node; the CNI creates it to connect the pod. | 0, 6 |
| **VIP (Virtual IP)** | A single floating IP fronting the three API servers (via keepalived + HAProxy) so clients use one stable endpoint. | 3, 5 |
| **VLAN** | A logically separated LAN segment; we split management traffic from application/LB traffic onto different VLANs. | 4 |
| **Network namespace** | A private, isolated network stack (own interfaces/routes) — the boundary that gives each pod its own network. | 0, 6 |

---

*End of Appendix A. The companion `repo/` holds every manifest and Dockerfile referenced
in the chapters above, organized by bootstrap order.*
