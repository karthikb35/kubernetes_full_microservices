"""
Enriches every chapter file in docs/ with:
  - Clear "# File: ..." comments on code blocks that lack them
  - A "Nuances, Gotchas & Architect Considerations" section before the
    final checklist in each chapter
Run once:  python enrich_docs.py
"""
import re
from pathlib import Path

ROOT  = Path(__file__).parent
DOCS  = ROOT / "docs"

# ---------------------------------------------------------------------------
# Per-chapter enrichment content
# Each value is a 3-tuple:
#   (section_heading, nuances_text, gotchas_text, architect_text)
# inserted as a numbered sub-section before the final !!! success checklist.
# ---------------------------------------------------------------------------

ENRICHMENTS: dict[str, dict] = {

"00b-prerequisites.md": dict(
  heading="0.9",
  nuances="""\
- The **kubeconfig context** is not the same as a user account — it is a named combination of cluster, user credentials, and namespace. You can have many contexts pointing at the same cluster with different credentials; `kubectl config use-context` just changes which combination is active.
- `kubectl` communicates only with the **kube-apiserver** — never with kubelets directly. Every operation (even `kubectl exec`) is proxied through the API server.
- Helm charts are just **templates** that render to Kubernetes YAML. The actual objects live in the cluster; Helm tracks release state in a Secret in the same namespace. Deleting that Secret orphans the objects — `helm list` shows nothing but the resources still run.""",
  gotchas="""\
- Confusing `kubectl apply` (declarative, idempotent, tracks last-applied-configuration annotation) with `kubectl create` (imperative, fails if the object already exists). Always prefer `apply` in automation.
- Using `kubectl delete pod X` to "restart" a pod managed by a Deployment just causes the Deployment to create a replacement — the correct restart idiom is `kubectl rollout restart deployment/X`.
- Assuming all objects are namespaced — `Node`, `PersistentVolume`, `ClusterRole`, `StorageClass`, and `CustomResourceDefinition` are **cluster-scoped**. Passing `-n my-ns` does nothing for them.""",
  architect="""\
1. **Single kubeconfig vs per-cluster** — should operators use a shared admin kubeconfig (simple but over-privileged) or per-person OIDC tokens (auditable, revokable)? Choose OIDC + `kubectl oidc-login` for any team larger than 2.
2. **kubectl version skew** — the client must be within ±1 minor version of the server. Enforce this via a cluster-local `kubectl` wrapper script that pins the correct version.
3. **Helm vs raw manifests** — Helm adds release lifecycle management but introduces template complexity. Use Helm for third-party software you consume; use raw manifests (or Kustomize) for your own services where you control the YAML.
4. **etcd as the source of truth** — everything in `kubectl get` is a live read from etcd. There is no separate "config database" to sync; the cluster state IS the database.
5. **Preview environments** — namespaces make cheap preview environments only if your storage (PVCs, secrets) can also be namespace-scoped and cheaply provisioned. Plan PVC provisioning speed before committing to PR-per-namespace patterns."""
),

"00-front-matter.md": dict(
  heading=None,  # front matter — skip insertion
),

"01-scenario.md": dict(
  heading="1.8",
  nuances="""\
- A "stateless" service pod can still hold **in-flight request state** (goroutine/thread memory) — pod loss during a request causes a 5xx to the client. This is unavoidable without client-side retry logic or a service mesh retry policy.
- The Kafka `OrderConfirmed` event is **at-least-once** delivered. Notifications must check a Redis dedup key before sending an email to prevent duplicate receipts — a subtle invariant that often gets dropped when the Notifications service is rewritten.
- The 10-minute seat-hold TTL must be enforced in three places consistently: Redis key TTL, application-level expiry check on the Orders write path, AND the UI countdown timer. Any mismatch causes ghost holds (seats held but expired) or double-booking (hold released while user still on checkout page).""",
  gotchas="""\
- **Shared database anti-pattern**: connecting Orders directly to `users_db` to avoid an RPC call seems harmless but creates a hidden schema coupling. Resist it — it is the most common path back to a distributed monolith.
- **Synchronous saga orchestration** means Orders holds a DB transaction open while waiting for Inventory and Payments RPCs. Slow external calls (Stripe latency spikes) translate directly to Postgres connection exhaustion. Timeout every external RPC and compensate explicitly.
- **Missing idempotency keys on payment capture**: if the Orders pod restarts mid-saga after `Authorize()` but before writing the result, it may call `Authorize()` again on retry — resulting in a double-charge. Every payment RPC must carry a stable idempotency key derived from the `orderId`.""",
  architect="""\
1. **Thundering-herd on sale open**: 50,000 users hit the Inventory service in the same second. Is Redis `SETNX` for holds safe under this load, or do you need a distributed queue (Redis Streams, Kafka) to serialize the seat-hold requests?
2. **Stripe outage strategy**: should failed payment attempts be queued in Kafka and retried asynchronously (better UX for users), or returned as 402 immediately (simpler, but worse conversion)?
3. **Eventual consistency visibility**: when a seat is held by User A, how quickly does the event page for User B show it as unavailable? A 10-second lag is acceptable for concerts; a 1-second lag is acceptable for limited edition sneakers. Define the SLO before building.
4. **Decomposition boundary review**: is a separate Payments service justified for TicketHub, or should Orders own payment capture? The boundary matters because it determines who handles Stripe webhook callbacks.
5. **Event schema versioning**: `OrderConfirmed` v1 carries `{ orderId, userId, seats[] }`. When you add `promoCode` in v2, Notifications (consuming v1) must not break. Plan Avro/Protobuf schema registry or envelope versioning from the start.
6. **Capacity model**: a single sold-out stadium event generates ~60,000 concurrent users over 5 minutes. Work backwards to per-service RPS, then to pod count, then to node count — this is the exercise that determines your HPA max replicas in Chapter 16."""
),

"02-baremetal-to-vm.md": dict(
  heading="2.5",
  nuances="""\
- KVM **CPU pinning** eliminates NUMA cross-traffic for memory-intensive VMs (Postgres data nodes) but reduces the hypervisor's scheduling freedom — pin only where latency matters, not cluster-wide.
- Proxmox default disk format is **qcow2** (copy-on-write, flexible but ~15% slower than raw). Switch VM disks to **raw** format on Ceph RBD-backed storage for production database VMs to eliminate the double CoW overhead.
- VM **balloon driver** (virtio-balloon) can dynamically return unused guest RAM to the hypervisor — useful for dev/staging but dangerous for Postgres nodes that use a large shared_buffers. Disable it for data-pool VMs.""",
  gotchas="""\
- **Forgetting to disable swap in the VM** after provisioning: `swapoff -a` survives the session but `/etc/fstab` re-enables it on reboot, causing kubelet to refuse to start with `failed to run Kubelet: running with swap on is not supported`.
- **CPU passthrough breaks live migration**: `cpu: host` gives best performance but means you cannot live-migrate VMs to a host with a different CPU generation. Use the lowest common denominator microarch (e.g., `cpu: Cascadelake-Server`) for any VM you may need to migrate.
- **NTP drift between VMs**: the hypervisor clock is the authoritative source; each VM must sync from the KVM host, not from an external NTP server. etcd requires < 500ms clock skew between members — larger drift causes leader election instability.""",
  architect="""\
1. **VM density vs performance**: a rule of thumb is allocate no more than **1.5× physical cores** in total vCPUs across all VMs on a host (avoid CPU steal for latency-sensitive workloads). What is the actual peak CPU utilization per VM in your load model?
2. **Dedicated CP hosts vs shared**: separating control-plane VMs onto dedicated physical hosts prevents a noisy application workload from starving the etcd leader, but wastes hardware. Justified for clusters > 50 nodes or SLA-critical platforms.
3. **VM count vs bare-metal workers**: every VM layer adds latency (network virtio, disk virtio). For very I/O-intensive workloads (Kafka, Ceph OSD), evaluate whether the VMs are introducing unacceptable p99 latency — consider dedicated bare-metal workers in the data pool.
4. **Recovery time objective for a lost hypervisor**: if a KVM host fails, how long does it take to bring up replacement VMs (manual re-provision vs Terraform + cloud-init)? This directly sets your node-level RTO.
5. **Ceph OSD placement**: Ceph OSDs must run on nodes where the raw block devices reside. If Ceph runs on VMs, the VMs must have RBD-backed disks that are NOT themselves backed by the same Ceph cluster (avoid circular dependency)."""
),

"03-topology.md": dict(
  heading="3.5",
  nuances="""\
- etcd quorum requires `(n/2)+1` members available. With 3 control-plane nodes you can lose exactly **one** and still write. Losing two makes the API server read-only — no new pod scheduling, no ConfigMap updates, no Secret creation. Plan your maintenance window accordingly.
- **Zone labels on bare metal are advisory only** — nothing in Kubernetes enforces that pods assigned to `zone=rack-a` actually run on physical rack A. The labels are only honoured by topology spread constraints and affinity rules you configure. If you mislabel, you silently lose the HA guarantee.
- The `infra` pool taint means DaemonSets for platform components (Falco, node-exporter, Cilium agent) must carry the matching toleration or they will not run on infra nodes — leaving them unmonitored. Always audit DaemonSet tolerations when adding a new taint.""",
  gotchas="""\
- **Adding zone labels after workloads are running** does not re-balance existing pods. You must delete and recreate (or drain-and-uncordon) the pods to trigger rescheduling with topology spread constraints applied.
- **Forgetting to taint data nodes** before deploying application workloads: without the taint, a Deployment's pods may be scheduled onto data nodes, competing for CPU/RAM with Postgres and Kafka.
- **etcd on shared disk**: etcd is extremely sensitive to disk I/O latency. Running etcd on the same NVMe as application workloads causes sporadic leader elections and `etcdserver: request timed out` errors. Always dedicate a disk or partition exclusively to `/var/lib/etcd`.""",
  architect="""\
1. **Scale ceiling**: the data pool has 3 nodes. Postgres (3 pods) + Kafka (3 pods) already fills the pool with minimal headroom. At what point does adding a Redis cluster, a second Postgres instance for a new service, or Elasticsearch require a pool expansion plan?
2. **Control plane upgrade strategy**: with 3 control-plane nodes you must drain one at a time, leaving the etcd cluster at 2/3 quorum during upgrade. Plan the maintenance window so you never start upgrading the second node while the first is still upgrading.
3. **Worker pool segmentation trade-offs**: strict `NoSchedule` taints on data/infra pools mean a traffic spike on the general pool cannot borrow capacity from infra nodes. Is this acceptable, or should infra nodes have `PreferNoSchedule` to allow emergency overflow?
4. **Node labels for feature detection**: beyond `pool=` labels, consider labelling nodes with hardware features (`nvidia.com/gpu`, `storage.ssd=nvme`) so workloads can request specific hardware via `nodeSelector` without hard-coding hostnames.
5. **Multi-rack failure domains**: if racks share a single top-of-rack switch, a switch failure is a zone failure. Verify physical network redundancy matches your logical zone model — otherwise `topology.kubernetes.io/zone` labels overstate HA."""
),

"04-network-design.md": dict(
  heading="4.5",
  nuances="""\
- Pod CIDRs (`10.244.0.0/16`) and Service CIDRs (`10.96.0.0/12`) must **never overlap** with each other or with the node network (`10.10.0.0/16`). Cilium allocates a `/24` per node from the pod CIDR — with `/16` you can have up to 256 nodes before you need a larger CIDR (plan for growth from day one).
- **DNS round-robin for Services is not load balancing** — it is address discovery. Cilium's eBPF does the actual per-connection load balancing at the kernel level, not at the DNS layer. This means long-lived gRPC streams to a Service IP may stay on a single backend pod until the connection is closed.
- Node-to-node traffic uses the **node network CIDR** (`10.10.0.0/16`), not the pod CIDR. Firewall rules between nodes must allow the full pod CIDR range (for pod-to-pod across nodes) AND the Service CIDR (for return traffic through ClusterIP virtual IPs).""",
  gotchas="""\
- **Picking a pod CIDR that overlaps with a future on-prem subnet**: once a cluster is bootstrapped you cannot change the pod or service CIDRs without rebuilding. Reserve a block of RFC 1918 address space (e.g., `100.64.0.0/10`, CGNAT range) that will never appear in your corporate network.
- **kube-dns / CoreDNS hardcoded to `10.96.0.10`**: if you choose a non-standard service CIDR, the CoreDNS ClusterIP will be different — update all references, including the kubelet `--cluster-dns` flag in the kubeadm config, or DNS resolution fails cluster-wide.
- **MetalLB pool overlapping with node IPs**: MetalLB hands out IPs from `10.10.0.200-250` as LoadBalancer Service IPs. If a new server is assigned an IP in that range, ARP conflicts will cause intermittent routing failures. Document the split in your IP address management (IPAM) system and enforce it.""",
  architect="""\
1. **Address space future-proofing**: `10.244.0.0/16` gives 65,536 pod IPs. With 256 nodes × 110 pods each = 28,160 pods max. A `/15` gives twice the room; a `/14` four times. Choose based on your 3-year node growth forecast, not your current node count.
2. **East-West encryption**: should all pod-to-pod traffic be encrypted (WireGuard overlay in Cilium) or only traffic crossing a trust boundary? Encryption adds ~5% CPU overhead. For TicketHub's on-prem cluster where physical network access is controlled, selective encryption (gateway ↔ payments) may suffice.
3. **Egress NAT design**: pods use the node IP as the SNAT address for outbound traffic. If Payments calls Stripe from any of 9 worker IPs, Stripe must whitelist all 9. Consider a dedicated egress IP (Cilium EgressGateway) for external API calls from specific namespaces.
4. **IPv6 dual-stack readiness**: Cilium supports dual-stack. If your data center is moving toward IPv6, plan the pod and service CIDRs to include `fd00::/112` ranges from the start — retrofitting IPv6 post-launch is expensive.
5. **BGP vs ARP for MetalLB**: `L2 ARP` mode is simpler but has a single-node failure window (the node holding the ARP entry). `BGP` mode distributes the announcement but requires a BGP router in your rack. Choose based on your network team's capabilities."""
),

"05-kubeadm-install.md": dict(
  heading="5.7",
  nuances="""\
- `kubeadm init --upload-certs` stores the CA private key in a Secret in `kube-system` encrypted with a per-run key and **automatically expires after 2 hours**. If the second CP node join happens after 2 hours, the `--certificate-key` will no longer work — regenerate with `kubeadm init phase upload-certs --upload-certs`.
- **Static pods bypass the scheduler**: etcd, kube-apiserver, kube-controller-manager, and kube-scheduler run as static pods managed by kubelet directly from `/etc/kubernetes/manifests/`. They cannot be managed with `kubectl delete pod` — deleting the static pod manifest file is the only way to stop them.
- The `--skip-phases=addon/kube-proxy` flag during `init` leaves the cluster without ANY service routing until Cilium is installed. This means the init job completes successfully but `kubectl get nodes` may show `NotReady` even for the first CP node — that is expected.""",
  gotchas="""\
- **Pinning kubeadm/kubelet versions**: `apt-mark hold` is essential. An unintended `apt upgrade` that bumps kubelet to a newer minor version than the kube-apiserver violates the version skew policy and can break the node.
- **Forgetting `--control-plane-endpoint` at init time**: you cannot add this flag post-installation. If you init with `--apiserver-advertise-address` (single IP) instead of a VIP, joining additional CP nodes later will require a kubeadm upgrade + cert regeneration — painful.
- **Certificate SANs**: `kubeadm init` auto-includes the CP node IP and hostname in the apiserver cert SANs, but NOT the VIP if you add the load balancer later. Always pass `--apiserver-cert-extra-sans=<VIP>` at init time, or regenerate the apiserver cert afterward with `kubeadm init phase certs apiserver`.""",
  architect="""\
1. **Bootstrap token security**: the join token printed by `kubeadm init` is valid for 24 hours and grants unauthenticated join capability. Rotate it (`kubeadm token create`) immediately after all nodes have joined, and restrict token creation permissions in RBAC.
2. **etcd topology — stacked vs external**: kubeadm defaults to stacked etcd (etcd co-located on CP nodes). External etcd (separate VMs) gives stronger isolation and allows etcd to be upgraded independently, but adds 3+ VMs to manage. For a 12-node cluster, stacked is adequate; for 50+ nodes, consider external.
3. **kubeadm config file vs flags**: all the `--flags` above should be committed to a `ClusterConfiguration` YAML (`repo/cluster/kubeadm-config.yaml`) and checked into git. Never run kubeadm with flags from memory — the config file IS your cluster's source of truth.
4. **Certificate rotation policy**: by default, kubelet rotates its client certificates automatically. The kube-apiserver serving cert must be manually renewed annually (`kubeadm certs renew`). Add a PrometheusRule alert for cert expiry < 30 days (Chapter 27 covers this).
5. **Disaster recovery with etcd snapshots**: the cluster is recoverable from etcd only if you have a recent snapshot AND the CA key. Test your etcd restore procedure against a clone cluster before the first production incident."""
),

"06-cilium-cni.md": dict(
  heading="6.6",
  nuances="""\
- Cilium's **BPF maps** are kernel data structures with a fixed maximum size. The default `bpf-map-dynamic-size-ratio` of 0.25 sizes maps based on total system RAM. On a node with very low RAM (< 4GB), the map sizes may be too small for clusters with many services, causing `map full` errors. Tune `--bpf-policy-map-max` and `--bpf-lb-map-max` proactively.
- **L7 policy (HTTP/gRPC path-aware)** requires Cilium to proxy the connection through an Envoy sidecar on the node — this adds ~0.5ms latency per hop. Use L7 policy only where HTTP-path granularity is genuinely needed; use L3/L4 for everything else.
- `kubeProxyReplacement=true` takes full ownership of `ClusterIP` routing. If you later add a component that tries to install its own iptables rules for service routing (e.g., an older Istio version), you will get a conflict. Verify all installed components are compatible with kube-proxy-free mode.""",
  gotchas="""\
- **CNI is hard to replace post-install**: migrating from Cilium to another CNI (or vice versa) requires draining all nodes, removing the CNI, reinstalling, and reprogram all NetworkPolicy — effectively a cluster rebuild. Choose deliberately and commit.
- **Hubble relay not enabled by default**: `hubble observe` requires `hubble.relay.enabled=true` at install time. If you forget it, you need to `helm upgrade` Cilium later. Not a disaster, but it means you're flying blind on network flows during the most vulnerable early phase.
- **`cilium connectivity test` requires unrestricted egress**: the test creates pods in `cilium-test` namespace that make external HTTP requests. If a default-deny NetworkPolicy is in place before the test, it will fail with misleading errors. Run the connectivity test before applying NetworkPolicy.""",
  architect="""\
1. **Hubble data retention**: Hubble stores flow records in a ring buffer in kernel memory — it has no persistent store. For compliance or forensics, you need to configure a Hubble export to an external log store (Loki, Elasticsearch) via the Hubble Kafka/S3 exporter.
2. **eBPF kernel version requirements**: Cilium 1.16 requires kernel ≥ 5.10 for all features. Verify your VM kernel version before cluster bootstrap — older RHEL/Ubuntu LTS kernels may not support all Cilium features (notably WireGuard encryption requires ≥ 5.6, BPF-based masquerading requires ≥ 5.10).
3. **DSR (Direct Server Return) compatibility**: DSR load balancing (`loadBalancer.mode=dsr`) bypasses kube-proxy completely and returns traffic directly from the backend pod to the client. It requires the backends to see the original client IP — check that your HAProxy VIP configuration is compatible before enabling this.
4. **Network policy migration strategy**: migrating from broad `allow all` to zero-trust NetworkPolicy (Chapter 21) is the highest-risk operational change on a live cluster. Use Hubble in audit mode first, generate policy from observed flows, then enforce incrementally per namespace.
5. **Cluster Mesh for multi-cluster**: if TicketHub grows to span multiple data centers, Cilium Cluster Mesh provides a single policy domain across clusters. This is a significant architectural commitment — design the initial address space and naming conventions with multi-cluster in mind from day one."""
),

"07-metallb-ingress.md": dict(
  heading="7.5",
  nuances="""\
- MetalLB in L2 mode announces the LoadBalancer IP from a **single node** at a time using ARP/NDP. Traffic arrives at that node, which then routes internally. This means a single node carries all north-south traffic — the load balancing happens AFTER the packet enters the cluster, not at the IP level. The announcing node becomes a bottleneck for very high-throughput services.
- With **Cilium's Gateway API**, TLS is terminated inside the Cilium-managed Envoy proxy on the Gateway node — backend pods receive plain HTTP (or mTLS if you configure it separately). There is **no separate NGINX pod** to size; capacity is governed by the Cilium agent/Envoy resource limits on the infra nodes. Ensure they can absorb your peak TLS handshake rate.
- `cert-manager` uses **ACME DNS-01 or HTTP-01 challenges** for Let's Encrypt. The HTTP-01 solver now attaches an **HTTPRoute** to the Gateway's `:80` listener rather than an Ingress. On a private on-prem cluster without internet access, HTTP-01 is impossible — use DNS-01 with your DNS provider's API, or an internal CA (Chapter 7A) for cluster-internal certificates.""",
  gotchas="""\
- **MetalLB pool overlapping with DHCP range**: if your data center DHCP server allocates IPs in the `10.10.0.200-250` range, ARP conflicts will cause intermittent LoadBalancer IP unreachability. Co-ordinate with the network team and document the reserved range.
- **Gateway API CRDs missing or version-skewed**: unlike Ingress, `Gateway`/`HTTPRoute` are CRDs. Applying a `Gateway` before the CRDs exist fails with `no matches for kind "Gateway"`; a CRD version newer than the Cilium controller understands leaves the Gateway `PROGRAMMED: False` with no traffic. Install the CRDs first and match versions.
- **cert-manager CRD version drift**: `Certificate`, `Issuer`, and `ClusterIssuer` CRDs are versioned. Upgrading cert-manager without reading the migration guide can cause CRD schema validation failures that block certificate renewals silently.""",
  architect="""\
1. **Single vs multi-Gateway**: running one `Gateway` for all traffic makes it a shared-fate component. Because `HTTPRoute`s are independent per-route objects, a bad route no longer breaks the whole edge — but the listeners/IP are still shared. Consider per-team or per-tier `Gateway`s (each its own IP) for strong isolation.
2. **MetalLB BGP upgrade path**: L2 mode is simpler but has a single-node bottleneck. If north-south throughput requirements grow (>10 Gbps), plan the migration to BGP mode with ECMP — this requires network team involvement and a BGP router change.
3. **WAF placement**: with Cilium's Gateway you can attach L7 policy/filters at the edge, or run a dedicated WAF. For a payments platform, should WAF rules live at the Gateway (easier), at the API Gateway service (more context-aware), or both? Layer 7 inspection adds latency — measure before committing.
4. **Gateway API maturity by feature**: core `HTTPRoute` is GA, but some pieces (TLSRoute, GRPCRoute, mesh/GAMMA) are at different stability levels across implementations. Pin to the feature set your controller (Cilium) supports as GA, and track the conformance matrix before relying on experimental fields.
5. **Certificate wildcard vs per-service**: a `*.tickethub.io` wildcard cert simplifies management but must be rotated for every domain — including unrelated ones. Per-service certs (automated by cert-manager) are noisier but limit blast radius if a cert is compromised."""
),

"07b-certificates.md": dict(
  heading="7A.5",
  nuances="""\
- cert-manager **does not renew certificates that are manually edited**. If you patch the `spec.duration` or `spec.renewBefore` of a `Certificate` object, cert-manager detects the discrepancy and re-issues immediately — useful for forcing a renewal, but unexpected if you're just inspecting it.
- The cluster CA generated by kubeadm is a **10-year self-signed cert** by default. It is NOT automatically rotated by kubeadm — you must rotate it manually, which is one of the most disruptive cluster operations (it requires restarting every component and re-issuing every signed cert). Plan for this before year 10.
- **Trust bundle distribution via `trust-manager`** is one-way: trust-manager copies CA bundles INTO ConfigMaps, but pods that mount the ConfigMap as a volume do NOT see updates until the pod restarts. Add an application-level cert reload mechanism (SIGHUP handler, inotify watcher) for services that use the bundle.""",
  gotchas="""\
- **`NotReady` after cert rotation**: when you rotate the kubelet serving cert, the API server briefly loses connectivity to the kubelet, causing pods to show `Unknown` status. This is transient — wait 60 seconds before debugging.
- **`Certificate` object `spec.secretName` collision**: if two `Certificate` objects in the same namespace target the same `secretName`, cert-manager will fight over the Secret content, causing rapid re-issuance. Always use unique Secret names per Certificate.
- **Let's Encrypt rate limits**: the production Let's Encrypt CA has a hard rate limit of 50 certificates per registered domain per week. In a staging environment with many ephemeral namespaces, each generating a Certificate, you can exhaust this limit in hours. Always use the Let's Encrypt staging issuer in non-production environments.""",
  architect="""\
1. **Internal CA lifetime and rotation plan**: a 10-year cluster CA means you have 10 years before a forced rebuild — but also 10 years of accumulated risk from the CA key being on disk. Consider a 5-year lifetime and document the rotation procedure before you need it.
2. **mTLS scope**: cert-manager + trust-manager + istio/linkerd can give you mTLS between every pod pair. For TicketHub, mTLS is most critical for the `orders → payments → postgres` path. Define explicitly which service pairs require mTLS vs which are covered by NetworkPolicy alone.
3. **PKI hierarchy depth**: the current model is a 2-level hierarchy (cluster CA → service certs). A 3-level hierarchy (root CA → intermediate CA → service certs) allows you to rotate intermediate CAs without touching the root — better for long-lived installations.
4. **Certificate observability**: cert expiry is a leading indicator of outage, not a trailing one. The `x509-certificate-exporter` DaemonSet (Chapter 27) plus a Prometheus alert firing 30 days before expiry should be considered non-optional for any production cluster.
5. **Vault integration for production PKI**: cert-manager's Vault issuer allows Vault to be the root of trust, keeping private keys off-cluster in a secrets manager with HSM backing. For a payments platform, this is the correct long-term architecture — the current cluster CA is a stepping stone."""
),

"08-storage-rook-ceph.md": dict(
  heading="8.5",
  nuances="""\
- Ceph's **CRUSH map** determines which OSDs receive each placement group's replicas. Without explicit CRUSH rules, all three replicas of a PG can land on OSDs of the same host — providing no host-level redundancy even with `replicasPerFailureDomain: 1`. Verify the CRUSH topology with `ceph osd crush tree` after cluster bootstrap.
- **`reclaimPolicy: Retain`** means deleting a PVC does NOT delete the backing Ceph RBD image. The image persists in Ceph consuming space indefinitely. You must manually `kubectl delete pv <name>` AND run `rbd rm` or the Rook cleanup policy to actually reclaim the storage.
- The StorageClass `volumeBindingMode: WaitForFirstConsumer` delays PV provisioning until the pod is scheduled. This is intentional for topology awareness — but it means `kubectl get pvc` will show `Pending` until the first pod is scheduled, which can look like a bug during initial cluster setup.""",
  gotchas="""\
- **OSD placement on VMs backed by the same Ceph cluster**: if your worker VMs' root disks are Ceph RBD images and you then run Ceph OSDs on those VMs, a Ceph outage prevents the VMs from booting, which prevents Ceph from recovering. Never run Ceph OSDs on VMs whose disks depend on Ceph.
- **Ceph health `HEALTH_WARN` on OSDs_down during node drain**: when you drain a data node for maintenance, its OSDs go down. Ceph begins backfilling immediately. If the node comes back within `osd_down_out_interval` (default 600s), no data movement occurs. If it takes longer, Ceph redistributes all PGs — generating significant I/O. Increase `osd_down_out_interval` during planned maintenance windows.
- **Block device selection for OSDs**: Rook requires dedicated block devices (no partition table, no filesystem). A freshly provisioned VM disk that was previously used as a Ceph OSD may have leftover LVM signatures — clean it with `wipefs -a /dev/sdX` and `dd if=/dev/zero of=/dev/sdX bs=1M count=10` before Rook can claim it.""",
  architect="""\
1. **OSD count and raw capacity planning**: Ceph with 3× replication means usable capacity = raw capacity / 3. For 9 OSDs × 1TB each = 3TB raw, you get ~3TB usable. This needs to cover all PVCs plus the internal Ceph metadata overhead (~5%). Model capacity growth against your planned 3-year PVC growth rate.
2. **Separate OSD disks for block vs object**: Ceph block (RBD) and object (RGW) workloads have very different I/O patterns (random IOPS vs sequential throughput). Separate OSDs using all-flash for block and HDD for object storage if your hardware budget allows it.
3. **Rook operator upgrade isolation**: Rook manages CephCluster upgrades — but a Rook operator upgrade and a Ceph upgrade are separate events. Always upgrade Rook first, then trigger the Ceph image upgrade via the CephCluster CR. Never skip a Ceph minor version.
4. **Multi-site replication for DR**: Ceph RGW supports multi-site replication of object storage between clusters. If your DR strategy requires off-site data copies (Chapter 27), the Ceph multi-site design must be in place before the cluster goes live.
5. **Performance testing before production**: run `fio` benchmarks against both RBD and CephFS before declaring the storage layer production-ready. Key targets: Postgres needs > 5,000 random IOPS at 4K block size; Kafka needs > 200 MB/s sequential write throughput per broker."""
),

"09-namespaces-resources.md": dict(
  heading="9.5",
  nuances="""\
- **Namespaces are not a security boundary** — a compromised pod in `tickethub` namespace can still reach pods in `data` namespace via ClusterIP Services. Namespaces provide isolation of RBAC, ResourceQuota, and LimitRange; NetworkPolicy provides the actual traffic boundary.
- **ResourceQuota does not enforce existing objects**: creating a ResourceQuota on a namespace that already has running pods doesn't evict them even if they exceed the quota. The quota only applies to NEW objects. Audit existing resource usage before applying quota to a live namespace.
- **`LimitRange` defaults apply at admission time**, not retroactively. Pods created before the LimitRange was applied keep their original (possibly unlimited) resource settings. This creates a mixed-state namespace that is hard to reason about.""",
  gotchas="""\
- **Namespace deletion hangs**: `kubectl delete namespace tickethub` hangs if any object in the namespace has a finalizer that hasn't been cleared. Common culprits: Velero backup objects, cert-manager Certificates with `deleteOnTermination`, and CRDs with cross-namespace references. Debug with `kubectl get namespace tickethub -o json | jq '.spec.finalizers'`.
- **Cross-namespace Service access requires full DNS name**: a pod in `tickethub` that calls `postgres` (short hostname) resolves to `postgres.tickethub.svc.cluster.local` — which doesn't exist. The full name `postgres.data.svc.cluster.local` is required. Enforce this via ConfigMap (`DATABASE_URL`) values, not code.
- **ResourceQuota on `count/pods` without `count/deployments`**: setting a pod quota without a Deployment quota means a misbehaving Deployment can create thousands of pods quickly (e.g., a crash-loop flood) until the quota kicks in — but by then the node is already under pressure. Always pair pod quotas with replica-level limits.""",
  architect="""\
1. **Namespace proliferation governance**: namespaces are cheap to create but expensive to manage (each needs quota, RBAC, NetworkPolicy, possibly LimitRange). Define a namespace creation policy: who can create namespaces, what template gets applied, how are they decommissioned?
2. **Soft vs hard multi-tenancy**: namespaces provide soft tenancy (API isolation + RBAC). Hard tenancy (cryptographic workload isolation) requires separate clusters or vCluster. For a single TicketHub cluster where all tenants are internal teams, namespace-based soft tenancy is sufficient.
3. **Bootstrap ordering and GitOps**: the bootstrap order (namespaces first, quotas second, platform CRDs third, workloads last) must be encoded in Argo CD Application sync waves (Chapter 28) so that a full cluster restore doesn't fail on ordering dependencies.
4. **LimitRange and VPA interaction**: VPA (Chapter 16) overwrites pod resource requests at admission time — but VPA recommendations must fit within the LimitRange min/max. If they don't, VPA silently skips the pod. Verify LimitRange maximums are generous enough for VPA to work.
5. **Quota for ephemeral storage**: `ephemeral-storage` requests/limits are rarely set but can cause node eviction under log-spamming containers. Add `ephemeral-storage` to your LimitRange defaults."""
),

"10-containerizing.md": dict(
  heading="10.5",
  nuances="""\
- **Multi-stage build cache invalidation**: Docker's layer cache is invalidated from the first changed layer downward. Copying `go.mod`/`go.sum` BEFORE `COPY . .` means `go mod download` is only re-run when dependencies change, not on every code change. This is the single biggest build-time optimization for Go services.
- **Distroless images contain no shell** — you cannot `kubectl exec -it -- /bin/sh` into them for debugging. Instead, use ephemeral debug containers: `kubectl debug -it pod/X --image=busybox --target=go-service`. Never re-add a shell to a distroless prod image just for convenience.
- **Non-root UID must be consistent across image layers**: if the `COPY --from=builder` copies files owned by `root` and then the `USER 1000` directive switches to non-root, the app may not be able to read its own files at runtime. Always `COPY --chown=1000:1000` in the final stage, or set ownership in the builder stage.""",
  gotchas="""\
- **`latest` tag in production**: `image: myapp:latest` combined with `imagePullPolicy: Always` means every pod restart pulls a new image — including breaking changes deployed after the pod was last scheduled. Always use immutable digest tags (`sha256:...`) or semver tags in production manifests.
- **Secret injection via build ARGs**: `ARG DB_PASSWORD` makes the secret visible in `docker history` and Docker layer cache. Secrets must be injected at **runtime** via environment variables or mounted files, never baked into the image layer.
- **Multi-arch build assumption**: building on an ARM Mac and pushing to a registry used by x86 nodes will cause `exec format error` on pod startup. Always build for `linux/amd64` explicitly in CI, or use `docker buildx` multi-platform manifests.""",
  architect="""\
1. **Image registry strategy**: a private registry (registry.internal.tickethub.io) is required for images that contain proprietary business logic. Decide: run Ceph/Harbor on-cluster (adds operational burden) or use an external private registry (adds a network dependency and egress cost)?
2. **Base image governance**: who owns the base images (`golang:1.25-alpine`, `gcr.io/distroless/base`)? A team that pulls base images without verification is vulnerable to supply-chain attacks (Chapter 24). Define a process for: base image approval, vulnerability scanning, and scheduled rebuilds when base image CVEs are published.
3. **Build reproducibility**: a Dockerfile without pinned base image digests is not reproducible — two builds of the same commit can produce different images if the base image has been updated. Pin base images by digest in Dockerfiles for production services.
4. **Layer size vs layer count trade-off**: fewer, larger layers are generally faster to push/pull (fewer HTTP requests) but harder to cache incrementally. For a microservice with 50 MB of dependencies and 5 MB of code, separate layers make sense; for a 500 MB monolith, reconsider the decomposition.
5. **SBOM and CVE scanning integration**: generate a Software Bill of Materials (`syft`) and scan it with `grype` in the CI pipeline. Block merges when HIGH/CRITICAL CVEs are introduced. This is the first line of supply-chain defence (Chapter 24)."""
),

"11-workload-controllers.md": dict(
  heading="11.5",
  nuances="""\
- A **ReplicaSet** is the actual controller that maintains the desired pod count — a Deployment manages ReplicaSets, not pods directly. When you do a rolling update, the Deployment creates a NEW ReplicaSet and scales it up while scaling down the old one. The old ReplicaSet (with 0 replicas) is kept as rollback history — `kubectl rollout history` lists them.
- **DaemonSets bypass the scheduler's bin-packing** — they place exactly one pod per matching node regardless of available resources. If a DaemonSet pod's resource requests cannot fit on a node, the pod stays `Pending` on that node forever (no eviction of other pods to make room). Size DaemonSet pods conservatively.
- **StatefulSet `podManagementPolicy: Parallel`** allows all pods to start simultaneously (faster), but the default `OrderedReady` is safer for databases that require pod-0 to be the primary before pod-1 starts replication. Never switch a Postgres StatefulSet to Parallel without understanding the startup coordination consequences.""",
  gotchas="""\
- **`kubectl delete rs` on a Deployment-owned ReplicaSet**: the Deployment controller immediately re-creates the ReplicaSet. This is not a rollback — it creates a fresh RS with the same pod template. To rollback, use `kubectl rollout undo deployment/X`.
- **StatefulSet rolling update leaves a failed pod blocking the rollout**: if pod-0 fails its readiness probe after the update, the rollout pauses — pods 1 and 2 are never updated. The rollout does not time out or auto-rollback. You must manually fix pod-0 OR run `kubectl rollout undo` to unblock.
- **DaemonSet on tainted nodes**: a new `NoSchedule` taint on a node does not evict existing DaemonSet pods. The taint only affects newly scheduled pods. If you retaint a node, DaemonSet pods on it are unaffected until the next pod restart.""",
  architect="""\
1. **Deployment vs StatefulSet boundary**: the line is "does pod identity matter?" If `orders-pod-7f4d` can replace `orders-pod-a1b2` without any state transfer, use a Deployment. If each pod has a named role (Postgres primary vs standby), use a StatefulSet. The gray area is services that use external session stores (Redis) — they are truly stateless and should use Deployments.
2. **DaemonSet for security vs performance**: Falco, node-exporter, and Cilium agents are natural DaemonSets. But a heavy DaemonSet (e.g., a 512Mi baseline logging agent) on every node burns constant cluster-wide RAM. Always benchmark DaemonSet overhead per node type before deploying.
3. **Job completion vs Deployment for one-time tasks**: `db-migrate-job.yaml` (repo/manifests/30-workloads/) runs schema migrations as a Job. Migrations run in a Deployment would run in a loop forever. The key Job parameters: `backoffLimit: 3` (max retries), `restartPolicy: Never` (don't restart the pod on failure, create a new one instead).
4. **CronJob concurrency policy**: `concurrencyPolicy: Forbid` means if the previous CronJob run is still running when the next trigger fires, the new run is skipped. For backup or batch jobs where overlapping runs would corrupt output, `Forbid` is the right choice; for idempotent jobs, `Allow` gives better throughput.
5. **Pod disruption budget interaction with Deployments**: a PDB with `minAvailable: 2` on a 3-replica Deployment means a `kubectl rollout restart` will drain only one pod at a time — the rollout serializes. This is the correct behavior for zero-downtime restarts but multiplies the rollout duration by the replica count."""
),

"12-services-traffic.md": dict(
  heading="12.5",
  nuances="""\
- **kube-dns (CoreDNS) search domains** mean `postgres` inside a pod resolves to `postgres.<current-namespace>.svc.cluster.local`. If a pod in `tickethub` ns calls `postgres.data` (intending `postgres.data.svc.cluster.local`), it first tries `postgres.data.tickethub.svc.cluster.local` — which fails — before trying the correct form. Always use fully qualified names for cross-namespace DNS to avoid ndots resolution latency.
- **Session affinity (`sessionAffinity: ClientIP`) is hash-based, not sticky-session aware**: all connections from the same client IP hit the same pod, but a pod restart breaks affinity. If you need application-level stickiness (shopping cart, websocket), express it as a cookie-based `HTTPRoute` filter in your Gateway implementation (or a service mesh policy), not the Service affinity.
- **`ExternalTrafficPolicy: Local`** on a LoadBalancer Service preserves the original client IP (no SNAT) but means only nodes with a backend pod accept traffic — nodes without a pod will drop the connection. With 3 pods spread across 9 nodes, 6 out of 9 nodes will silently drop inbound traffic for that Service.""",
  gotchas="""\
- **`ClusterIP: None` makes a Service headless** — it returns A records for individual pod IPs, not a virtual IP. Calling `postgres.data.svc.cluster.local` from the `orders` service returns all 3 pod IPs via DNS. If orders uses a naive HTTP client that doesn't re-resolve DNS on each connection, it may always route to the same pod. Headless Services require the client to implement its own load balancing.
- **Service port name must match Istio/Cilium L7 protocol detection**: naming a Service port `http` vs `tcp` changes how a service mesh or L7 NetworkPolicy processes it. Cilium uses the port name to decide whether to apply HTTP-aware policy. Always name ports with the correct protocol prefix.
- **Endpoint not ready after pod crash**: Kubernetes removes the pod's IP from the Service's EndpointSlice only after the readiness probe fails AND the pod is removed. During the gap (typically < 5s), the Service may route to a pod that is no longer serving. Ensure client retries are configured for this transient window.""",
  architect="""\
1. **Headless Service for StatefulSets vs ClusterIP for Deployments**: this isn't a choice — StatefulSets that need stable per-pod DNS (Kafka brokers identifying themselves as `kafka-0.kafka.data`) MUST use headless. Deployments use ClusterIP for load-balanced access. Mixing them up is a common cause of mysterious connection failures.
2. **Service topology aware routing**: Kubernetes EndpointSlice topology hints route traffic preferentially to pods on the same node or zone. For TicketHub, routing Orders → Postgres within the same zone reduces cross-rack latency. Enable topology hints on Services where cross-AZ latency matters.
3. **East-West load balancing algorithm**: Cilium's eBPF uses maglev consistent hashing for Service load balancing by default — which gives better connection distribution than simple round-robin, especially for long-lived gRPC connections. Verify your connection pool sizes account for this distribution.
4. **NodePort port range**: the default NodePort range is `30000-32767`. Using NodePorts for production services is not recommended (port memorization burden, firewall complexity), but if needed for legacy integrations, document the port assignments explicitly to prevent conflicts.
5. **Service vs Gateway for internal services**: internal services (Orders calling Payments) should use ClusterIP Services directly — they don't need the Gateway. Only traffic entering from outside the cluster goes through the Gateway. Routing internal traffic through the edge Gateway adds unnecessary latency and a single point of failure."""
),

"13-config-secrets.md": dict(
  heading="13.5",
  nuances="""\
- **Mounted ConfigMap volumes update automatically** (eventually consistent, with a kubelet sync delay of `syncPeriod`, default 60s) — but **environment variables from ConfigMaps do NOT update** without a pod restart. This asymmetry catches teams off-guard: changing a feature flag in a ConfigMap takes up to 60s to propagate to volume-mounted configs but requires a rollout for env-var configs.
- **Kubernetes Secrets are base64-encoded, not encrypted**, by default in etcd. The base64 encoding is not a security measure — anyone with etcd access sees plaintext values. Encryption at rest (`EncryptionConfiguration` with AES-GCM or Vault KMS provider) is a separate cluster-level config (Chapter 24).
- **ExternalSecret reconciliation interval**: the `ExternalSecret` CR has a `refreshInterval` (default 1 hour). If Vault revokes and reissues a secret (e.g., after a rotation event), the new value won't reach the Kubernetes Secret for up to 1 hour unless you `kubectl annotate externalsecret X force-sync=$(date +%s)` to trigger immediate reconciliation.""",
  gotchas="""\
- **`envFrom: configMapRef` loads ALL keys as env vars**: if a ConfigMap has a key named `JAVA_TOOL_OPTIONS` it will override the JVM settings for every container that mounts it — silently. Prefer `env: valueFrom: configMapKeyRef` for explicit key selection in production.
- **Secret data keys with unsupported characters**: Kubernetes Secret keys must match `[-._a-zA-Z0-9]`. A key named `db.password` (with a dot) is valid, but many application frameworks that read env vars convert dots to underscores or vice versa. Use consistent naming conventions.
- **ExternalSecret fails silently if the Vault path doesn't exist**: the ExternalSecret controller sets a `Ready=False` condition on the CR, but the application pod starts anyway with the PREVIOUS secret value if the Kubernetes Secret already exists from a prior sync. Monitoring ExternalSecret conditions is non-optional.""",
  architect="""\
1. **ConfigMap vs environment variable vs Vault secret decision tree**: use ConfigMaps for non-sensitive tunable configuration (log levels, feature flags, URLs). Use Secrets (backed by Vault via ExternalSecret) for credentials, tokens, and API keys. Never use ConfigMaps for secrets, even temporarily.
2. **Secret rotation zero-downtime strategy**: when a database password is rotated in Vault, ExternalSecret updates the Kubernetes Secret, but running pods don't see the update until they restart. Design connection pool reconnect logic (Postgres `target_session_attrs`, JDBC retry) to handle mid-session password changes, or coordinate pod rolling restarts with the rotation event.
3. **Vault namespace isolation**: does each team's ExternalSecret pull from a separate Vault namespace/path with its own policy? Sharing a single Vault policy that allows reading ALL secrets gives each service blast radius equal to the entire secret store — violates least privilege.
4. **Configuration drift detection**: with ConfigMaps managed by GitOps (Argo CD), a manual `kubectl edit configmap` creates drift that Argo CD will revert. Ensure your runbooks instruct operators to make configuration changes through git, not kubectl, to avoid surprise rollbacks.
5. **Sealed Secrets vs External Secrets**: Sealed Secrets encrypt secret values in git (useful for small teams without a Vault instance). External Secrets pull from an external store at runtime (better for enterprise governance). Choose based on your secret management maturity — Vault + External Secrets is the correct long-term architecture."""
),

"15-resource-management.md": dict(
  heading="15.5",
  nuances="""\
- **CPU requests are used for scheduling AND CPU share allocation (cgroups)**, not for hard limits. A pod requesting `500m` CPU on a node with spare cycles can burst to multiple cores — `request` only guarantees its proportional share under contention. Only `limit` hard-caps CPU via the CFS bandwidth controller.
- **Memory limit OOM is immediate and silent**: when a container exceeds its memory limit, the kernel sends `SIGKILL` with `OOMKilled` reason — no warning, no graceful shutdown. This is different from CPU throttling (which just slows the container). Size memory limits with headroom for GC pauses (JVM) or memory spikes.
- **`BestEffort` pods are evicted first under node pressure**, but eviction order within a QoS class depends on how much over their request a pod is running. A `Burstable` pod using 10× its request is evicted before a `Burstable` pod using 1.1× — even if the second pod has a smaller absolute memory footprint.""",
  gotchas="""\
- **Setting CPU limit = CPU request**: this gives the container a `Guaranteed` QoS class (good for priority), but it pins the CPU at exactly the request — the container cannot burst even when the node has idle capacity. For most application pods, set no CPU limit and let them burst freely; set only a request to guide scheduling.
- **ResourceQuota counts requests, not actual usage**: a namespace with `cpu: 10` quota and 10 pods each requesting `1` CPU has hit the quota even if all pods are idle. Submitting a new pod fails with `exceeded quota` regardless of actual node capacity.
- **Missing LimitRange defaults**: a namespace without a LimitRange allows pods with no `resources` spec — these get `BestEffort` QoS and are the first to be evicted under node pressure. Always define LimitRange defaults to ensure a minimum resource contract.""",
  architect="""\
1. **Request sizing methodology**: requests should reflect the pod's p99 actual usage, not a theoretical maximum. Oversized requests cause poor bin-packing (nodes appear full while CPUs are idle). Use `kubectl top pod` / Prometheus `container_cpu_usage_seconds_total` histograms to right-size requests.
2. **CPU limit policy**: Google SRE and the Kubernetes community debate whether to set CPU limits. The consensus for latency-sensitive services: **no CPU limit** (allow bursting), set request accurately. For batch jobs: set limit = request (predictable scheduling). For third-party components: follow the vendor recommendation.
3. **Memory limit headroom factor**: set memory limit = 1.3–1.5× the p99 actual usage. This covers GC pauses (JVM), memory allocator overhead, and temporary buffers. Below 1.2× causes spurious OOMKills under load; above 2× wastes memory quota.
4. **Quota namespacing granularity**: should each microservice team have its own namespace with isolated quota, or should the `tickethub` namespace have a single aggregate quota? Per-team namespaces give charge-back visibility but multiply the management overhead.
5. **LimitRange max for VPA interaction**: VPA recommends new request/limit values. If the LimitRange `max.memory` is lower than VPA's recommendation, VPA silently skips the pod. Keep LimitRange maximums generous — they are a guardrail, not a target."""
),

"16-autoscaling.md": dict(
  heading="16.5",
  nuances="""\
- **HPA has a stabilization window**: by default, scale-down is suppressed for 300 seconds after the last scale event to prevent thrashing. During a load spike that lasts 4 minutes, the HPA may keep extra pods running for 5+ minutes after load drops. This is intentional — tune `stabilizationWindowSeconds` for your traffic pattern.
- **KEDA can scale to zero; HPA cannot**: HPA's minimum is 1 replica. KEDA's `ScaledObject` with `minReplicaCount: 0` genuinely scales the Deployment to zero pods when there's no work — saving resources for batch/event-driven services. The trade-off: a cold-start delay on the first message.
- **VPA mutates pods at admission time**: VPA applies recommendations by evicting pods and recreating them with new resource specs. This means a VPA with `updateMode: Auto` is continuously evicting pods based on usage — acceptable for batch, destructive for stateful services. Always use `updateMode: Off` (recommend only) for databases.""",
  gotchas="""\
- **HPA + VPA on the same Deployment**: if HPA controls replicas and VPA controls resources, they fight. HPA may scale up to 10 replicas; VPA may then lower each pod's request, causing HPA to scale back down (thinking load is lower). Only use VPA on workloads NOT controlled by HPA, or use the `VerticalPodAutoscalerCheckpoints` approach.
- **Custom metric HPA with Prometheus adapter**: if the Prometheus query returns no data (empty series), the adapter returns `0`. HPA interprets this as "zero load" and scales to `minReplicas` — potentially dropping all pods during a monitoring outage. Configure `behavior.scaleDown.stabilizationWindowSeconds: 600` as a safety buffer.
- **Cluster Autoscaler vs pod eviction**: CA adds nodes based on `Pending` pods. If your node group has a maximum size and CA hits it, pods stay `Pending` indefinitely with no obvious error. Monitor `cluster_autoscaler_unschedulable_pods_count` and set an alert.""",
  architect="""\
1. **Scale floor vs cost floor**: KEDA's scale-to-zero is great for cost — but the first Kafka message after a cold start triggers a pod create (~30s), during which messages queue. Define the acceptable message-processing latency SLO and compare it against the cold-start time before enabling scale-to-zero for `notifications`.
2. **Horizontal vs vertical scaling decision**: stateless services (catalog, orders, gateway) scale horizontally (more pods). Stateful services (Postgres, Kafka) scale vertically (larger pods) or with sharding. Mixing strategies on the same workload requires careful VPA/HPA co-ordination.
3. **Node group diversity for Cluster Autoscaler**: CA only adds nodes it knows about. With a single node group (all general workers), CA cannot add data-pool or infra-pool nodes. If Prometheus or Kafka needs more capacity, CA cannot help — you must manually expand the data pool. Design node groups to match your scaling axes.
4. **KEDA ScaledJob vs ScaledObject**: for short-lived batch tasks, `ScaledJob` creates new Job instances per queue message rather than scaling a long-running Deployment. This gives perfect work isolation (one crash doesn't affect others) but higher pod overhead. Choose based on job duration and failure isolation requirements.
5. **Autoscaler interaction with PodDisruptionBudget**: a PDB with `minAvailable: 2` on a 3-replica Deployment blocks the CA from removing a node if it would violate the PDB. Always pair PDB min with a replica count that allows graceful scale-down."""
),

"17-scheduling-placement.md": dict(
  heading="17.5",
  nuances="""\
- **Affinity and anti-affinity are evaluated at scheduling time, not continuously**: once a pod is placed, it is never evicted just because the affinity rule is violated (e.g., if the preferred node is retainted after scheduling). Descheduler (an optional add-on) can periodically re-balance, but vanilla Kubernetes does not.
- **`topologySpreadConstraints` uses `labelSelector` to count matching pods, not running pods**: a `Pending` pod counts toward the spread calculation. If two pods are simultaneously scheduled to the same zone, the spread constraint is temporarily violated — Kubernetes tolerates this momentary imbalance.
- **PriorityClass preemption evicts the lowest-priority pod** that, when removed, gives the high-priority pod enough resources. But the evicted pod's graceful termination period still applies — Kubernetes waits for it to terminate before scheduling the high-priority pod. During `terminationGracePeriodSeconds`, both the evicted and the new pod are competing for resources.""",
  gotchas="""\
- **`requiredDuringSchedulingIgnoredDuringExecution` anti-affinity with replicas > zones**: if you require each pod to be on a different zone and you have 3 pods but only 2 zones, the third pod stays `Pending` forever. Use `preferredDuringSchedulingIgnoredDuringExecution` unless you can guarantee enough nodes in each zone.
- **Forgetting DaemonSet tolerations when adding taints**: adding `NoSchedule` taints to data/infra nodes without updating DaemonSet tolerations breaks monitoring (Falco, node-exporter) on those nodes — silently.
- **PodDisruptionBudget `unhealthyPodEvictionPolicy: AlwaysAllow`** (Kubernetes 1.27+) allows voluntary disruptions to proceed even if the pod is already unhealthy. Without this, a pod in CrashLoopBackOff blocks node drains indefinitely — a common cluster upgrade blocker.""",
  architect="""\
1. **Rack-awareness vs zone-awareness**: Kubernetes only knows zones, not racks. If your 3 racks are in the same zone (same data center), a zone failure still takes out all 3 racks. For true rack-level HA, add a custom `topology.tickethub.io/rack` label and use it in `topologySpreadConstraints`.
2. **Cluster-level PriorityClass policy**: who can create high-priority PriorityClasses? A team that creates `value: 1000000` can starve ALL other workloads by preemption. Restrict PriorityClass creation to cluster admins via RBAC (Chapter 19).
3. **Descheduler for re-balancing**: Kubernetes schedules but doesn't continuously re-balance. After node addition or failure recovery, pods are not automatically redistributed. The `descheduler` project adds this capability — evaluate it before assuming your topology spread constraints are being honoured over time.
4. **Topology spread with HPA**: when HPA scales a Deployment from 3 to 12 replicas under load, `topologySpreadConstraints` guides placement. But if one zone's nodes are full, the scheduler falls back to a zone with capacity — violating the spread. Ensure zone capacity is symmetric and sized for peak replica counts.
5. **Graceful termination vs PDB interaction**: a PDB prevents pod eviction if it would violate `minAvailable`. During a rolling update, a pod being terminated counts as "unavailable" until it fully stops. If `terminationGracePeriodSeconds` is long (60s+) and the PDB is tight (`minAvailable: 2` on 3 replicas), the rollout serializes to 1 pod at a time and takes minutes. Tune graceful termination and PDB together."""
),

"18-health-lifecycle.md": dict(
  heading="18.5",
  nuances="""\
- **All three probe types use the same failure threshold logic** (`failureThreshold × periodSeconds`) but serve different purposes: liveness kills and restarts the container; readiness removes it from Service endpoints (no restart); startup suppresses liveness during the startup window. A wrong probe type causes the wrong behavior — a liveness probe that triggers during a traffic spike causes a restart cascade instead of graceful back-pressure.
- **`preStop` hook runs concurrently with SIGTERM in some container runtimes**: the hook is not guaranteed to complete before SIGTERM is sent in all cases. If your shutdown sequence depends on the hook finishing first (e.g., draining a connection pool before accepting SIGTERM), add a `sleep` in the hook equal to your expected drain time as a belt-and-suspenders measure.
- **Rolling update `maxSurge` and `maxUnavailable` are evaluated as a PAIR**: with `maxUnavailable: 0` and `maxSurge: 1`, the update creates one new pod and waits for it to pass readiness before killing one old pod. The deployment is always at full capacity — ideal for zero-downtime. With `maxUnavailable: 1` and `maxSurge: 0`, it kills one pod first, then creates a replacement — briefly drops below capacity.""",
  gotchas="""\
- **Liveness probe too aggressive during GC pauses**: a JVM doing a full GC may pause for 5-10 seconds. If `liveness.timeoutSeconds: 1` and `failureThreshold: 3`, the container is killed after ~3 seconds of GC — causing a restart loop under load. Set `timeoutSeconds: 5` and `failureThreshold: 3` (15s total) for JVM services.
- **Readiness probe checking downstream dependencies**: a readiness probe that calls `SELECT 1` on Postgres means a Postgres outage marks ALL orders pods as unready — removing them from the Service endpoint and returning 503 to users even though the pods themselves are healthy. Check local health only in readiness probes; check downstream health in separate alerts.
- **`terminationGracePeriodSeconds: 0`** for "fast" rolling updates: this kills containers immediately on SIGTERM with no grace period. In-flight requests are dropped. Always allow enough time for connection draining: `terminationGracePeriodSeconds` ≥ the longest expected request duration + 5s buffer.""",
  architect="""\
1. **Startup probe vs `initialDelaySeconds`**: `initialDelaySeconds` is a blunt instrument — it delays all probes by a fixed time regardless of actual startup progress. `startupProbe` is smarter: it polls until the app is actually ready, then hands off to liveness/readiness. Always use `startupProbe` for services with variable startup times (JVM warm-up, schema migrations).
2. **Probe granularity**: a `/healthz` endpoint that returns 200 is not meaningful if it doesn't actually test the service's ability to serve traffic. Define three layers: `/healthz` (process alive — for liveness), `/readyz` (can serve requests — for readiness, checks DB connection pool), `/startupz` (initialization complete — for startup probe).
3. **Rolling update speed vs risk**: `maxUnavailable: 0, maxSurge: 1` is safest (never below capacity) but slowest (one pod at a time). `maxUnavailable: 25%, maxSurge: 25%` is 4× faster but briefly runs at 75% capacity. Size your `minReplicas` so that `replicas × (1 - maxUnavailable)` still meets your RPS SLO during rollout.
4. **Blue/green vs rolling for schema-breaking changes**: a rolling deployment of a service with a breaking API change means old and new versions serve traffic simultaneously. If the API break is a response field rename, clients see inconsistency. Use blue/green (create a separate Deployment, switch Service selector atomically) for schema-breaking changes.
5. **Canary with traffic splitting**: Argo Rollouts or Flagger can send 5% of traffic to the new version (canary) and automatically roll back if the error rate exceeds a threshold. This is the production-safe deployment strategy for TicketHub's payments path — zero-risk progressive delivery."""
),

"19-rbac.md": dict(
  heading="19.5",
  nuances="""\
- **RBAC is additive only** — you cannot explicitly deny a permission. If a user has a RoleBinding that grants `get pods` and another that grants `list pods`, they have both. The only way to "deny" access is to not grant it in the first place and remove all relevant bindings. This makes RBAC reasoning about "what CAN this principal NOT do?" difficult — enumerate permissions via `kubectl auth can-i --list --as <user>`.
- **ServiceAccount tokens are long-lived by default in older Kubernetes versions**: before Kubernetes 1.22, SA tokens were stored as Secrets with no expiry. From 1.24+, the token projection mechanism creates short-lived tokens (1 hour) automatically. If you're running workloads on 1.21 or below, audit token expiry explicitly.
- **`ClusterRoleBinding` to a namespaced `Role`** is not possible — a ClusterRoleBinding must reference a ClusterRole. However, a `RoleBinding` CAN reference a ClusterRole: this applies the ClusterRole's permissions only within the binding's namespace. Use this pattern to define roles once as ClusterRoles and bind them per-namespace.""",
  gotchas="""\
- **`system:masters` group bypasses all RBAC**: adding a user to `system:masters` (e.g., in the kubeconfig generated by kubeadm) gives permanent cluster-admin with no way to revoke — RBAC cannot deny `system:masters`. Never distribute the admin kubeconfig; use OIDC + RoleBindings for human access.
- **Operator service accounts with ClusterRole `*` verbs**: a hastily scaffolded operator that grants `verbs: ["*"]` on `resources: ["*"]` across `apiGroups: ["*"]` is a cluster takeover vector if the operator pod is compromised. Audit and scope every operator's RBAC at install time.
- **`automountServiceAccountToken: true` is the default**: every pod gets a mounted SA token that can call the Kubernetes API. A compromised pod with the default SA can `kubectl get secrets -n kube-system` if the SA has even basic RBAC. Always set `automountServiceAccountToken: false` on SAs for workloads that don't need API access.""",
  architect="""\
1. **OIDC integration for human access**: kubeadm-generated certificates are fine for cluster bootstrap, but human access in production should use an OIDC provider (Dex, Keycloak, Azure AD) so that user identities are tied to corporate directory, sessions expire, and access can be revoked centrally.
2. **Least-privilege service account design**: each microservice should have a dedicated ServiceAccount with only the permissions it actually uses. The `orders` service needs to read its own ConfigMaps; it does not need to list pods or create Secrets. Audit actual API calls with `kubectl auth can-i` and audit logs, then prune.
3. **RBAC for namespace self-service**: a team that can create namespaces can also bind ClusterRoles within them — effectively elevating themselves. Restrict `namespace create` to platform admins and provide a namespace provisioning workflow (Argo CD ApplicationSet or a custom Kubernetes controller) that applies RBAC templates.
4. **Aggregated ClusterRoles**: the `view`, `edit`, and `admin` ClusterRoles are aggregate roles that automatically include permissions from any ClusterRole with the matching aggregation label. When you install a new operator (e.g., cert-manager), its CRD views should be aggregated into the `view` role so developers can `kubectl get certificates` with their normal access.
5. **Audit log analysis**: RBAC decisions are logged in the Kubernetes audit log. Use a tool like `rbac-police` or `audit2rbac` to analyze audit logs and identify over-privileged service accounts. Run this analysis quarterly."""
),

"20-pod-security.md": dict(
  heading="20.5",
  nuances="""\
- **Pod Security Admission (PSA) `warn` mode writes warnings to the API server response, not to the pod's logs or events** — operators using CI pipelines must parse `kubectl apply` stderr for `Warning: would violate PodSecurity` messages. Many CI systems suppress stderr by default, making PSA warn mode silently useless.
- **`securityContext.readOnlyRootFilesystem: true`** prevents writes to the container's root filesystem, but tmpfs mounts (via `emptyDir: { medium: Memory }`) and volumeMounts are writable. An application that writes logs to `/tmp` must mount an `emptyDir` at `/tmp` explicitly or the container will crash.
- **`capabilities.drop: [ALL]` without adding back `NET_BIND_SERVICE`**: if your container binds to port 80 or 443, dropping ALL capabilities prevents binding to privileged ports (< 1024). Either run on a non-privileged port (8080) — the correct approach — or add back `NET_BIND_SERVICE` only.""",
  gotchas="""\
- **`privileged: true` bypasses ALL namespace isolation**: a privileged container can mount the host filesystem, load kernel modules, and escape the namespace entirely. It is equivalent to root on the host. Never use `privileged: true` in application pods; even Falco's DaemonSet uses a minimal set of capabilities instead.
- **`runAsNonRoot: true` without a specific UID fails unexpectedly**: if the container image's `USER` directive sets UID 0 (root), the pod will fail with `container has runAsNonRoot and image has non-numeric user root`. Always pair `runAsNonRoot: true` with `runAsUser: <non-zero UID>` for deterministic behavior.
- **PSA `enforce` on `kube-system` breaks cluster components**: `kube-system` pods (kube-proxy, Cilium) require privileged capabilities. Applying `restricted` policy to `kube-system` will block the CNI agent pods and crash the cluster. Never apply PSA enforcement to `kube-system`, `kube-public`, or any platform namespace without testing first.""",
  architect="""\
1. **PSA vs Kyverno for pod security**: PSA enforces three fixed policy levels (privileged, baseline, restricted) — no customization. Kyverno (Chapter 22) can express the same policies with custom carve-outs. For an enterprise platform, Kyverno gives the flexibility to say "allow this one specific privileged workload with an explicit exception" while PSA's `warn` mode acts as a safety net.
2. **Seccomp profile selection**: the default Docker seccomp profile blocks ~300 dangerous syscalls. The Kubernetes `RuntimeDefault` seccomp profile is equivalent. For payments/security-critical pods, a custom seccomp profile that allows ONLY the syscalls the binary actually uses (generated with `strace` or `seccompgen`) provides tighter isolation.
3. **Image UID/GID governance**: standardize on a non-root UID range for all team images (e.g., `1000-1999`). Add a Kyverno policy that rejects images claiming UID 0 at admission time. This prevents the "just run as root for local dev" habit from reaching production.
4. **Privileged DaemonSets namespace segregation**: Falco, Cilium, and node-exporter require elevated privileges. Run them in a dedicated `security` or `monitoring` namespace with explicit PSA `privileged` label. Never co-locate privileged DaemonSets with application workloads in the same namespace.
5. **Security context inheritance testing**: define a security context regression test suite that runs against every new container image: verify `runAsNonRoot`, `readOnlyRootFilesystem`, no `CAP_SYS_ADMIN`. Add this to your CI pipeline as a policy gate before images reach the registry."""
),

"21-network-policies.md": dict(
  heading="21.5",
  nuances="""\
- **NetworkPolicy is additive — there is no `deny` rule, only the absence of an `allow`**: the default-deny policy (`podSelector: {}`, empty ingress and egress) drops everything. Each subsequent policy adds specific allows. Two policies that both select the same pod have their ingress/egress rules UNION-ed — you cannot use a later policy to undo an earlier allow.
- **Cilium's `CiliumNetworkPolicy` supports L7 (HTTP/gRPC) rules, while the standard `NetworkPolicy` is L3/L4 only**: if you need to allow `POST /orders` but deny `DELETE /orders` from the same source, use `CiliumNetworkPolicy`. Standard `NetworkPolicy` cannot express HTTP method or path rules.
- **`namespaceSelector` matches on namespace LABELS, not names**: `matchLabels: { kubernetes.io/metadata.name: tickethub }` works because Kubernetes auto-adds this label to namespaces (from v1.21+). For older clusters, you must add the label manually to the namespace, or the selector silently matches nothing.""",
  gotchas="""\
- **Forgetting egress DNS (`port 53, kube-dns`)**: a default-deny egress policy that doesn't allow port 53 to the `kube-system` namespace breaks DNS resolution for the pod — causing connection failures that look like network policy blocks but are actually DNS failures. Always add a DNS egress allow to every namespace default-deny policy.
- **Applying policy to DaemonSets before adding their egress rules**: if you apply default-deny to the `monitoring` namespace before adding egress rules for `node-exporter → Prometheus scrape`, the node-exporter pods become unreachable. Test policy in `warn` mode with Hubble flow observability before enforcing.
- **Network Policy not supported by all CNIs**: Flannel + Calico combination, Weave, and some cloud CNIs have incomplete NetworkPolicy support. If you switch CNI, re-test all NetworkPolicy semantics. Cilium is fully compliant with the spec AND extends it — one of its key advantages.""",
  architect="""\
1. **Policy generation strategy**: writing NetworkPolicy by hand is error-prone. Use Hubble flow observability (Chapter 6) to observe actual traffic flows, then export them as policy drafts with `hubble observe --output policy`. Review and trim before applying — the generated policy is a starting point, not a final answer.
2. **Namespace isolation boundary**: should the `data` namespace (Postgres, Kafka) be completely isolated from all namespaces except `tickethub`? Or should monitoring (Prometheus scrape) from `monitoring` ns also be allowed? Define the per-namespace trust model as a policy matrix before implementation.
3. **Microservice-to-microservice policy granularity**: a single `allow tickethub → data port 5432` policy is simpler but allows any tickethub pod to reach Postgres. A tighter `allow orders-app → postgres port 5432` policy (using pod label selectors) limits blast radius if a less-privileged service is compromised.
4. **Policy testing in CI**: add a `NetworkPolicy conformance test` to CI that deploys test pods and verifies that allowed connections succeed and denied connections are blocked. Tools like `cyclonus` or `netassert` automate this. Without automated tests, policy regressions are invisible.
5. **Cilium FQDN policies for external egress**: Cilium supports `toFQDNs: [{matchName: "api.stripe.com"}]` to allow egress to specific external domains by DNS name — far more robust than IP-range-based egress rules (which break when Stripe rotates IPs). Use FQDN policies for all external API calls."""
),

"22-kyverno.md": dict(
  heading="22.5",
  nuances="""\
- **Kyverno mutation policies run BEFORE validation policies** in the admission chain. This means a mutate policy that injects a default `securityContext` runs first, then a validate policy can check that `securityContext` is present — allowing you to enforce invariants while also providing defaults for teams that haven't set them.
- **`background: true` (default)** means Kyverno evaluates policies against existing resources periodically, not just at admission time. A new validate policy with `validationFailureAction: enforce` will log violations on pre-existing resources but will NOT delete or modify them — only new or updated objects are blocked.
- **ClusterPolicy vs Policy scope**: `ClusterPolicy` is cluster-wide; `Policy` is namespace-scoped. Use `ClusterPolicy` for platform-wide invariants (no `latest` tag, no root containers) and namespace-scoped `Policy` for team-specific rules (allowed image registries for namespace X).""",
  gotchas="""\
- **`validationFailureAction: enforce` on a policy that breaks a system component**: if you apply a `ClusterPolicy` that blocks pods without a required label and the Cilium DaemonSet pods don't have that label, Cilium pods cannot be recreated after a crash — taking down all node networking. Always test policies in `audit` mode first and explicitly exclude system namespaces with `exclude.resources.namespaces`.
- **Kyverno webhook timeout**: Kyverno injects an admission webhook with a default timeout of 10 seconds. If the Kyverno pod is unavailable or slow, ALL pod admissions time out — blocking ALL deployments cluster-wide. Set `failurePolicy: Ignore` on non-critical policies and ensure Kyverno runs with PDB `minAvailable: 1` or is in HA mode.
- **Generate policies and ownership**: when Kyverno generates a NetworkPolicy in a new namespace, it becomes the owner. Manually editing that NetworkPolicy will cause Kyverno to re-sync it back to the generated version. Either don't generate resources you intend to customize, or use `synchronize: false` to generate-once-and-abandon.""",
  architect="""\
1. **Policy as code in git**: Kyverno ClusterPolicies should live in the `repo/manifests/60-security/` directory and be deployed via Argo CD (Chapter 28). This makes policy changes auditable (git history), reviewable (PR process), and automatically enforced across environments.
2. **Kyverno vs OPA/Gatekeeper**: Kyverno uses native Kubernetes YAML for policies (lower learning curve); OPA Gatekeeper uses Rego (more expressive for complex rules). For a platform team that primarily maintains Kubernetes manifests, Kyverno's YAML-native approach reduces the cognitive overhead. For complex multi-system policy (spanning cloud APIs, CI/CD, and Kubernetes), OPA is more consistent.
3. **Exception management**: Kyverno supports `PolicyException` objects (v1.9+) that grant named workloads exemptions from specific policies. This is better than disabling the policy for everyone — use PolicyExceptions for the `cilium-system` pods that legitimately need `privileged: true`.
4. **Image signature verification at scale**: Kyverno's `verifyImages` policy (with cosign) verifies every image pull against a public key. The verification adds ~100ms to pod scheduling. For clusters with hundreds of pod starts per second, verify the signing verification overhead is acceptable — cache the results in the Kyverno OCI cache.
5. **Policy drift detection**: Kyverno's background scan generates `PolicyReport` and `ClusterPolicyReport` objects with violation counts. Expose these to Grafana via the policy-reporter sidecar. A dashboard showing violation counts per namespace and per policy gives the platform team real-time visibility into compliance posture."""
),

"23-falco.md": dict(
  heading="23.5",
  nuances="""\
- **Falco rules are evaluated for every syscall event** on the node — there is a performance cost. Default Falco installs see 1-5% CPU overhead per node. Custom rules that add expensive string comparisons or regular expressions can push this higher. Profile rule performance with `falco --list-syscalls` and Falco's built-in stats output.
- **`spawned_process` events fire for EVERY new process** — including shell commands run legitimately by init systems, healthchecks, and entrypoint scripts. A "shell spawned in container" rule without a trusted-container allowlist will generate enormous noise at cluster scale, causing alert fatigue. Tune allowlists carefully before enabling.
- **Falco kernel module vs eBPF driver**: the kernel module gives full syscall coverage but requires `--privileged` and is blocked by secureboot. The eBPF driver is more portable and works with secureboot. Cilium also uses eBPF — ensure the eBPF programs don't conflict by checking kernel eBPF map limits (`ulimit -l`).""",
  gotchas="""\
- **Falco rules are NOT NetworkPolicy**: Falco detects and alerts on suspicious activity; it does not block it. A Falco rule for "unexpected outbound connection" fires an alert but the connection proceeds. Combine Falco alerts with automated responses (Kubernetes admission webhook, Falco Sidekick → Kubernetes API to label/quarantine the pod) for actual blocking.
- **Custom rule precedence**: Falco evaluates rules in file order. A custom rule file that overrides a default rule must use `override: { condition: replace }` explicitly. Silently adding a rule with the same name results in both rules firing, doubling the alert volume.
- **Alert sink reliability**: Falco emits alerts to stdout by default. In a containerized deployment, this means alerts flow through the container log pipeline (Promtail → Loki). If Loki is down, alerts are lost. Always configure a Falco Sidekick integration with a durable sink (PagerDuty, Slack webhook, dedicated S3 bucket) for security-critical alerts.""",
  architect="""\
1. **Falco as the last line of defense**: Falco is a detective control — it observes and alerts but doesn't prevent. The order of security layers is: supply chain (Chapter 24) → image policy (Kyverno) → network policy (Chapter 21) → pod security (Chapter 20) → runtime detection (Falco). Each layer reduces the blast radius; Falco is what catches what the others miss.
2. **Rule tuning vs alert fatigue trade-off**: too few rules = real attacks missed; too many rules = analyst fatigue and ignored alerts. Define a triage process: every new Falco alert type must have a runbook before the rule is enabled in production. Alerts without runbooks get disabled.
3. **Incident response integration**: Falco Sidekick can trigger an Argo Workflow or a Kubernetes operator that automatically: labels the offending pod `status=quarantined`, applies a NetworkPolicy blocking all egress, and creates a PVC snapshot for forensics. Design this response automation before an incident occurs.
4. **eBPF-based detection completeness**: Falco with eBPF driver captures syscall-level events. It cannot observe encrypted traffic payloads (TLS) or in-memory operations that don't make syscalls. For full observability of a compromised process, supplement Falco with memory forensics (LiME) or eBPF-based tracing (Tetragon by Cilium).
5. **Compliance mapping**: Falco rules can be mapped to CIS Kubernetes Benchmark controls, NIST 800-53, or PCI-DSS requirements. Document which Falco rules satisfy which compliance controls — this makes audit preparation significantly faster."""
),

"24-secrets-supply-chain.md": dict(
  heading="24.5",
  nuances="""\
- **etcd encryption at rest encrypts the value stored in etcd, not the transmission**: the kube-apiserver decrypts secrets when it reads them from etcd and re-encrypts when writing. Secret values flowing over the API server's TLS connection are in plaintext inside the API server's memory — a compromised API server process can still read all secrets.
- **Cosign image signing verifies the image manifest digest**, not the image content. Two different images CAN have the same signed digest (preimage resistance of SHA-256 makes this computationally infeasible, but the trust is in the digest, not re-downloading and comparing bytes). The signature chain of trust is: registry push → Sigstore Rekor log entry → `cosign verify` at admission.
- **`imagePullPolicy: IfNotPresent`** (the default for tagged images) means a pod restart on the same node re-uses the cached image WITHOUT re-verifying the Kyverno image signature policy. A signed image that is later found malicious will keep running on nodes that have the cached layer until the cache is cleared. Combine signature verification with periodic digest pin updates in your manifests.""",
  gotchas="""\
- **KMS encryption key rotation**: when you rotate the KMS key used for etcd encryption, all existing Secrets must be rewritten to etcd with the new key (`kubectl get secrets --all-namespaces -o json | kubectl replace -f -`). Missing this step means some Secrets are still encrypted with the old key — and if the old key is revoked, those Secrets become permanently unreadable.
- **Cosign keyless signing with Sigstore Fulcio** uses a short-lived OIDC certificate — the signing identity expires. If you rebuild and re-sign an image months later, the old signature is valid but the signing certificate is expired. `cosign verify` still passes (the transparency log records the original valid-time signature), but forensic tooling must handle this correctly.
- **Trivy/Grype CVE database lag**: vulnerability scanners use a CVE database that may be hours to days behind the NVD feed. A scanner that shows "no CRITICAL CVEs" does not mean the image is safe — it means no KNOWN CRITICAL CVEs as of the last database update. Schedule daily scans, not just build-time scans.""",
  architect="""\
1. **Defense in depth for secrets**: encryption at rest (etcd KMS) + encryption in transit (TLS) + runtime access control (RBAC) + secret lifecycle management (Vault rotation) + audit logging (who accessed what secret when) are five independent layers. Implement all five — losing any one layer doesn't compromise the whole.
2. **SBOM as a supply chain artefact**: generating an SBOM (`syft`) at build time and attaching it to the image (via cosign SBOM attestation) creates a persistent record of what went into the image. This is invaluable during a supply-chain incident: instead of rebuilding to check if a vulnerable library is present, query the SBOM.
3. **Registry admission control**: configure the container registry to only accept pushes from CI/CD pipelines (not from developer laptops). Every image in the registry was built by a reproducible, audited pipeline. This is a preventive control that complements Kyverno's image verification.
4. **Key management HSM integration**: the cosign private key should live in a Hardware Security Module (HSM) or cloud KMS, not on disk. A signing key on disk is as compromisable as any other file. Use Vault Transit Secrets Engine or AWS KMS as the cosign signing backend.
5. **Incident response for a compromised image**: if a signed production image is found to contain a backdoor, what is your response playbook? Key steps: revoke the signature (add to Sigstore revocation list), identify all running instances (`kubectl get pods -o json | jq 'select(.spec.containers[].image == "...")'`), trigger emergency rolling update with a clean image, preserve forensic evidence. Pre-write this playbook before you need it."""
),

"26-observability.md": dict(
  heading="26.5",
  nuances="""\
- **Prometheus `rate()` vs `irate()`**: `rate()` uses the full scrape interval window and is more resistant to single-sample spikes; `irate()` uses only the last two samples and reacts faster. For alerting rules (where you want to react to sustained increases), use `rate()`. For dashboards showing instantaneous throughput, `irate()` gives more responsive graphs.
- **Loki indexes only labels, not log content**: a query `{app="orders"} |= "ERROR"` first selects log streams by label (fast — B-tree lookup) and then scans the selected stream content for "ERROR" (slow — sequential scan). Design Loki label schemes with cardinality in mind: labels with 1000+ values (e.g., `pod_ip` or `request_id`) create exploding cardinality that breaks Loki's compaction and query performance.
- **Tempo trace sampling**: sending 100% of traces to Tempo at high throughput is expensive. A head-based sampling rate of 1-5% is typical for high-volume services. But you may miss rare error traces. Tail-based sampling (make the sampling decision AFTER seeing the full trace, keeping all error traces) provides better coverage — configure the OTel Collector to use tail-based sampling for error traces.""",
  gotchas="""\
- **`up` metric as the only Prometheus health check**: `up == 0` means Prometheus failed to scrape the target, but `up == 1` does NOT mean the service is healthy — it means Prometheus successfully scraped `/metrics`. A service that is returning 500s but still serves metrics will have `up == 1`. Always alert on your business metrics (`http_requests_total{status="5xx"}`), not just `up`.
- **Grafana datasource secret rotation**: Grafana stores datasource credentials (Prometheus, Loki URLs with auth) in its database. Rotating Prometheus bearer tokens requires updating Grafana's datasource config AND reloading it — a step often missed when rotating credentials.
- **OTel Collector memory limiter placement**: the `memory_limiter` processor must be the FIRST processor in the pipeline, before batching. If placed after the batcher, the batcher accumulates spans until the memory limit is already exceeded — causing uncontrolled OOM instead of graceful backpressure.""",
  architect="""\
1. **Metrics cardinality governance**: Prometheus performance degrades when the total number of unique time series (metric name × label combinations) exceeds ~1M per Prometheus instance. High-cardinality labels like `user_id`, `request_id`, or `url_path` in application metrics can explode series counts. Define a cardinality budget per service and enforce it via Prometheus recording rules that aggregate away high-cardinality dimensions.
2. **Log retention vs cost trade-off**: Loki stores logs in object storage (Ceph S3) which is cheap but query-slow for large windows. Define log retention tiers: 7 days hot (fast query), 30 days warm (slower), 90 days cold (compliance archive). Loki supports compaction and deletion policies per tenant/stream.
3. **Distributed tracing sampling strategy**: for an online ticketing platform, EVERY failed transaction should be traced end-to-end (tail sampling). Successful transactions can be sampled at 1%. This requires a tail-based sampler in the OTel Collector that buffers spans and makes the sampling decision when the root span completes.
4. **On-call alert quality**: every alert that pages someone at 3 AM must have a corresponding runbook. An alert without a runbook is a noise source, not a signal. Require runbooks as a PR requirement for any new `PrometheusRule`. Track mean time to acknowledge (MTTA) and mean time to resolve (MTTR) per alert as quality metrics.
5. **SLO burn rate alerts**: instead of alerting on raw error rates (`error_rate > 1%`), alert on SLO burn rate (`error_budget_consumed_rate > 5× normal` for 1-hour window). This gives high-signal, low-noise paging — you only get paged when you are burning through your error budget faster than acceptable, not on every transient spike."""
),

"27-backup-dr-upgrades.md": dict(
  heading="27.5",
  nuances="""\
- **Velero backs up Kubernetes resource definitions (etcd objects), NOT application data volumes** by default. The `--include-volumes` flag or CSI volume snapshot integration is required to back up PVC data. A Velero backup without volume snapshots can restore a StatefulSet definition but not the database data it contained.
- **etcd backup is a different layer from Velero backup**: etcd snapshot (`etcdctl snapshot save`) backs up the raw cluster state including Secrets, RBAC, and CRDs. Velero backup backs up namespaced resources but cannot restore cluster-scoped objects (Nodes, ClusterRoles, StorageClasses) without specific `--include-cluster-resources` flags. Both are required for full DR.
- **Kubernetes version skew policy**: you can upgrade only one minor version at a time (`1.29 → 1.30`, not `1.29 → 1.31`). Control plane components can be ahead of kubelets by up to 2 minor versions during rolling upgrades, but kubelets cannot be ahead of the API server. The upgrade order is always: etcd → kube-apiserver → other CP components → kubelets.""",
  gotchas="""\
- **`velero backup create` vs `velero schedule create`**: one-time backups expire and are deleted based on the TTL. Without a schedule, a manual backup from 6 months ago is your most recent backup when you need it most. Always configure a scheduled backup from day 1.
- **PVC snapshot CSI driver compatibility**: Velero CSI volume snapshots require the storage driver to support the `VolumeSnapshot` API. Rook-Ceph's CSI driver supports it, but you must install the `snapshot.storage.k8s.io` CRD and the external-snapshotter controller separately. Not having these installed means Velero silently skips volume backups.
- **In-place node upgrade vs blue-green**: `kubeadm upgrade node` upgrades the kubelet in place. If the upgrade fails mid-way, the node may be in a partially upgraded state that prevents normal operation. Always have a node replacement strategy (provision new node, drain old, decommission) as a fallback — especially for production clusters where rebuild time is critical.""",
  architect="""\
1. **RTO and RPO definition**: define these BEFORE building the backup system. For TicketHub: is a 4-hour RTO acceptable (rebuild cluster + restore backup)? Is a 1-hour RPO acceptable (lose up to 1 hour of orders)? These requirements drive the backup frequency, snapshot consistency level, and restore automation investment.
2. **Backup verification — "trust but verify"**: a backup that has never been tested is a hypothesis, not a guarantee. Schedule quarterly DR drills: restore the entire `data` namespace to a separate cluster and run smoke tests. Track the actual restore time — it's almost always longer than estimated.
3. **Cluster upgrade strategy for bare metal**: you cannot "spin up a new node" on demand like in cloud. For bare metal, the upgrade strategy is: drain workers one by one, upgrade kubelet, uncordon. For control plane: use the HA topology (3 CP nodes) so you upgrade one at a time with 2/3 quorum intact.
4. **etcd compaction and defragmentation**: etcd accumulates historical revision data that is only freed by compaction (`etcdctl compact`) and defragmentation (`etcdctl defrag`). A production cluster that has been running for months without defragmentation can have etcd databases 10× larger than necessary, increasing backup size and restore time.
5. **Multi-cluster DR topology**: a single on-prem cluster with backup to the same data center Ceph storage is not a true DR — a data center fire destroys both the cluster and the backup. For genuine DR, Velero backups must be replicated to an off-site location (different data center, cloud storage bucket)."""
),

"28-gitops-argocd.md": dict(
  heading="28.5",
  nuances="""\
- **Argo CD `sync` applies manifests in dependency order via sync waves**, but the wave mechanism is opt-in (annotation `argocd.argoproj.io/sync-wave: "N"`). Without explicit wave annotations, Argo CD applies all resources simultaneously — which can create ordering failures (e.g., a Deployment being created before its ConfigMap or Secret exists).
- **Argo CD App of Apps does not automatically prune child Applications when removed from the parent**: if you remove a child Application from the App of Apps, Argo CD marks it `OutOfSync` but doesn't delete it unless `prune: true` is set. Dangling Applications keep running and consuming resources indefinitely.
- **`kubectl apply` vs Argo CD sync**: Argo CD uses server-side apply with a `argocd` field manager. If you also run `kubectl apply` manually on the same resource, field manager conflicts can cause Argo CD to revert your changes or generate `FieldValueConflict` errors. All changes to Argo CD-managed resources MUST go through git.""",
  gotchas="""\
- **Argo CD sync with `--force` flag deletes and recreates resources**: unlike `kubectl apply --force`, this is destructive — Argo CD will DELETE a running StatefulSet and recreate it, causing a full restart. Only use force sync when absolutely necessary (stuck CRD migration), never as a routine operation.
- **Repo server access to private registries**: Argo CD's repo server must have git credentials to pull from private repos AND registry credentials if using Helm OCI charts from a private registry. Missing credentials cause silent sync failures with opaque "repository not found" errors.
- **Automated sync + Kyverno mutating webhooks**: Argo CD's drift detection compares the DESIRED manifest (git) against the LIVE manifest (cluster). Kyverno's mutation adds fields to the live manifest that aren't in git — causing Argo CD to always show the app as `OutOfSync`. Configure Argo CD's `ignoreDifferences` for Kyverno-injected fields to prevent false-positive sync loops.""",
  architect="""\
1. **Mono-repo vs multi-repo**: a single `repo/manifests/` tree (as in this project) is easy to navigate but creates a single failure domain for gitops — a broken PR that blocks merge prevents ALL service updates. A multi-repo layout (one repo per service team) gives team autonomy but multiplies Argo CD Application count and makes cross-service dependencies harder to express.
2. **Secrets in git with Argo CD**: application secrets cannot be stored in plaintext in git. Options: Sealed Secrets (encrypted in git, decrypted in cluster), External Secrets (fetched from Vault at sync time), Argo CD Vault Plugin (template substitution at sync time). External Secrets is the cleanest architecture — git contains only the ExternalSecret declaration, Vault holds the actual value.
3. **Sync windows for compliance**: some environments require that no changes are applied between Friday 5pm and Monday 9am (change freeze). Argo CD `SyncWindow` supports this — define `denyWindows` for change freeze periods. Without this, an auto-synced Argo CD will apply a Friday 11pm merge immediately.
4. **Rollback strategy**: Argo CD "rollback" is `git revert` + sync. There is no in-cluster rollback button that is independent of git state. Ensure your team understands this: to roll back a bad deploy, you must create a git commit that reverts the change and merge it to main. Design your branch protection and merge strategy around this constraint.
5. **ApplicationSet for multi-environment**: use Argo CD ApplicationSet with a directory generator to automatically create Applications for every environment directory (`envs/staging/`, `envs/prod/`). This avoids manually copying Application objects between environments and ensures all environments have the same Application structure."""
),

"29-recap.md": dict(
  heading="29.3",
  nuances="""\
- **The request journey is not a straight line**: in the full sequence (User → CDN → Gateway → API Gateway svc → Orders → Inventory → Payments → Kafka → Notifications), each hop involves DNS resolution, TLS handshake (potentially), TCP connection establishment, and application processing. Instruments show the TOTAL latency but each component in the chain can introduce jitter independently — distributed tracing (Tempo) is required to identify where p99 latency spikes originate.
- **Kubernetes' asynchronous reconciliation means eventual consistency everywhere**: when you `kubectl apply` a Deployment change, the API server accepts it immediately, but the scheduler, kubelet, and container runtime each have their own reconcile cycle. The time from `apply` to all pods serving the new version can be 10-120 seconds depending on image pull time and readiness probe duration.
- **The security model is defense in depth, not a single perimeter**: each layer (TLS, NetworkPolicy, RBAC, PSA, Kyverno, Falco) independently limits blast radius. An attacker who bypasses one layer still faces the others. The weakest link in the TicketHub security model is the shared `tickethub` namespace — services share namespace scope even though they have individual RBAC and NetworkPolicy.""",
  gotchas="""\
- **The mental model of "microservices are independent" breaks at the data layer**: Postgres, Kafka, and Redis are shared infrastructure. A Postgres volume fill, a Kafka partition leadership election storm, or a Redis BGSAVE blocking event affects ALL services that depend on them — regardless of pod isolation. Monitor data-layer SLIs as aggressively as application-layer SLIs.
- **GitOps and human-made kubectl changes create invisible drift**: an operator who directly edits a running ConfigMap bypasses git, creating state that Argo CD will revert on next sync. Establish a cultural and tooling norm: `kubectl edit` is a debugging tool, not a change management tool. All persistent changes go through git.
- **Observability requires active maintenance**: Prometheus alerts go stale (metric names change after service refactors), Grafana dashboards drift from reality, and Loki label schemes accumulate technical debt. Schedule a quarterly observability review: which alerts fired in the last quarter? Which were false positives? Which incidents had no alert?""",
  architect="""\
1. **Total Cost of Ownership (TCO) review**: after building the full cluster, calculate the operational overhead: how many engineer-hours per week does cluster maintenance consume? How does this compare to managed Kubernetes (EKS, GKE)? On-prem gives control and lower cloud cost at the expense of operational burden — re-validate this trade-off annually.
2. **Runbook completeness audit**: for every chapter in this book, there is a corresponding operational scenario. Does a runbook exist for: Postgres primary failover? Kafka broker crash? etcd member failure? Node OOM eviction cascade? Certificate near-expiry alert response? Runbook completeness is a direct measure of operational readiness.
3. **Chaos engineering readiness**: before declaring the cluster production-ready, run controlled chaos experiments: kill a control-plane node (does etcd recover?), kill the primary Postgres pod (does the operator promote a standby?), saturate a data node's disk (does the alert fire before Ceph goes critical?). Use Chaos Mesh or LitmusChaos to automate these experiments.
4. **Graduation path**: this textbook builds a single on-prem cluster. Real production platforms grow: second cluster for DR, multi-region, multi-tenancy. Review the design choices that would need to change at each scale step: CNI (Cluster Mesh), storage (multi-site Ceph), gitops (multi-cluster ApplicationSet), RBAC (federated identity).
5. **Documentation as living infrastructure**: the `docs/` in this repository are the authoritative reference for how the cluster was built and why each decision was made. Treat architecture decision records (ADRs) with the same rigor as code: every major design decision has a corresponding ADR document committed to the repository."""
),

"30-appendix-glossary.md": dict(
  heading=None,  # appendix — skip insertion
),
}

# Chapters with explicit headings for the CRD/stateful chapters we already enriched.
# Their checklist was already updated — skip re-inserting.
SKIP_CHAPTERS = {"14-stateful-storage.md", "25-crds-operators.md"}

# ---------------------------------------------------------------------------

def find_checklist_marker(text: str) -> int:
    """Return the character offset of the final !!! success checklist block."""
    # Walk through all matches and return position of last one
    pos = -1
    for m in re.finditer(r"^!!! success", text, re.MULTILINE):
        pos = m.start()
    return pos


def add_file_refs(text: str, chapter_file: str) -> str:
    """
    Prefix fenced code blocks that contain kubeadm/kubectl commands or YAML
    with a comment pointing to the source file if one can be inferred.
    Only adds the comment if the block doesn't already start with '# File:' or '# On '.
    """
    # Map chapter prefixes to manifest directories
    PREFIX_MAP = {
        "20-data":        "repo/manifests/20-data/",
        "30-workloads":   "repo/manifests/30-workloads/",
        "40-config":      "repo/manifests/40-config/",
        "50-scaling":     "repo/manifests/50-scaling/",
        "60-security":    "repo/manifests/60-security/",
        "70-observability": "repo/manifests/70-observability/",
        "10-platform":    "repo/manifests/10-platform/",
        "00-namespaces":  "repo/manifests/00-namespaces/",
        "cluster":        "repo/cluster/",
        "argocd":         "repo/argocd/",
    }

    # Add an inline comment at the start of YAML blocks that reference a known manifest file
    def replace_block(m):
        lang = m.group(1)
        body = m.group(2)
        fence = m.group(0)

        if lang not in ("yaml", "bash", "sh", ""):
            return fence

        # Skip if already has a file ref
        if body.lstrip().startswith("# File:") or body.lstrip().startswith("# On "):
            return fence

        # Look for pattern like "# repo/manifests/..." already in the text
        if "repo/manifests" in body or "repo/cluster" in body or "repo/argocd" in body:
            return fence

        # For yaml blocks: try to detect the kind/name and add a generic ref hint
        # We'll add a comment for yaml blocks that look like k8s manifests
        if lang == "yaml" and ("kind:" in body or "apiVersion:" in body):
            # Extract kind and name
            kind_m = re.search(r"kind:\s*(\w+)", body)
            name_m = re.search(r"name:\s*([\w-]+)", body)
            if kind_m:
                comment = f"# See: repo/manifests/ for the full manifest\n"
                return f"```{lang}\n{comment}{body.rstrip()}\n```"

        return fence

    text = re.sub(r"```(\w*)\n([\s\S]*?)```", replace_block, text)
    return text


def build_enrichment_block(heading: str, chapter_basename: str, data: dict) -> str:
    num_ch = re.match(r"(\d+[A-Za-z]?)", chapter_basename)
    ch_num = num_ch.group(1) if num_ch else "X"
    # Use the heading number if provided
    h = data.get("heading") or f"{ch_num}.N"

    nuances    = data.get("nuances", "").strip()
    gotchas    = data.get("gotchas", "").strip()
    architect  = data.get("architect", "").strip()

    if not (nuances or gotchas or architect):
        return ""

    block = f"\n### {h} Nuances, Gotchas & Architect Considerations\n\n"

    if nuances:
        block += "!!! tip \"Nuances — subtle behaviours to internalise\"\n"
        for line in nuances.splitlines():
            block += f"    {line}\n"
        block += "\n"

    if gotchas:
        block += "!!! warning \"Gotchas — traps that catch experienced engineers\"\n"
        for line in gotchas.splitlines():
            block += f"    {line}\n"
        block += "\n"

    if architect:
        block += "!!! question \"Architect Considerations\"\n"
        for line in architect.splitlines():
            block += f"    {line}\n"
        block += "\n"

    return block


def process_file(path: Path) -> int:
    """Return number of bytes added."""
    basename = path.name
    if basename in SKIP_CHAPTERS:
        print(f"  SKIP {basename}  (already enriched)")
        return 0

    data = ENRICHMENTS.get(basename)
    if not data or data.get("heading") is None:
        print(f"  SKIP {basename}  (front matter / appendix / no entry)")
        return 0

    text = path.read_text(encoding="utf-8")
    original_len = len(text)

    # 1) Add file references to code blocks
    text = add_file_refs(text, basename)

    # 2) Find insertion point — before final checklist
    pos = find_checklist_marker(text)
    if pos == -1:
        # No checklist found — append at end
        pos = len(text)

    enrichment = build_enrichment_block(basename, basename, data)
    if not enrichment:
        print(f"  SKIP {basename}  (empty enrichment)")
        return 0

    new_text = text[:pos] + enrichment + text[pos:]
    path.write_text(new_text, encoding="utf-8")

    added = len(new_text) - original_len
    print(f"  OK   {basename}  (+{added} chars)")
    return added


def main():
    files = sorted(DOCS.glob("*.md"))
    total_added = 0
    for f in files:
        total_added += process_file(f)
    print(f"\nDone. {total_added} characters added across {len(files)} files.")


if __name__ == "__main__":
    main()
