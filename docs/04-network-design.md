## <a name="ch4"></a>4. Network Design — Subnets, CIDRs, North-South & East-West

Networking is where most bare-metal Kubernetes projects stumble. Unlike a cloud, nobody hands you load balancers, routable pod networks, or DNS. As the architect you must **plan every IP range** and understand the two directions traffic flows: **North-South** (in/out of the cluster) and **East-West** (pod to pod).

### 4.1 The four networks in play

A Kubernetes cluster juggles **four distinct address spaces**. Confusing them is the #1 source of "my pods can't talk" incidents:

![Network layout](assets/diagrams/04-network-layout.png)

| Network | Example CIDR | Who lives here | Routable outside cluster? |
|---------|-------------|----------------|---------------------------|
| **Node / management** | `10.10.0.0/24` | VM NICs, SSH, API `:6443` | Yes (physical VLAN) |
| **MetalLB pool** | `10.20.0.0/24` | External IPs for `LoadBalancer` services | Yes (physical VLAN) |
| **Pod CIDR** | `10.244.0.0/16` | Every pod gets an IP here | No (Cilium overlay) |
| **Service CIDR** | `10.96.0.0/12` | Virtual `ClusterIP`s | No (virtual, kube-proxy/eBPF) |

!!! key "The golden rule of cluster CIDRs"
    The **Pod CIDR** and **Service CIDR** must **not overlap** with each other or with
    your **physical/VLAN** ranges. An overlap causes silent, maddening routing
    failures. Write the IP plan down **before** installing, and pick private ranges
    that are clearly distinct from your data-center subnets.

### 4.2 The IP plan (write this before installing)

| Purpose | Range | Notes |
|---------|-------|-------|
| Control-plane VMs | `10.10.0.11–13` | cp-1..3 |
| General workers | `10.10.0.21–24` | worker-gen-1..4 |
| Data workers | `10.10.0.31–33` | worker-data-1..3 |
| Infra workers | `10.10.0.41–42` | worker-infra-1..2 |
| API VIP (keepalived) | `10.10.0.10` | HAProxy front |
| MetalLB address pool | `10.20.0.100–200` | Ingress + any LB services |
| Pod CIDR | `10.244.0.0/16` | `kubeadm --pod-network-cidr` |
| Service CIDR | `10.96.0.0/12` | `kubeadm --service-cidr` (default) |

!!! note "VLAN separation"
    Put **management** traffic (VLAN 10) and **application/LB** traffic (VLAN 20) on
    separate VLANs. You don't want user traffic hitting the LoadBalancer pool to share
    a broadcast domain with etcd/SSH management. This is basic data-center hygiene that
    also limits blast radius.

### 4.3 North-South traffic — getting users *into* the cluster

**North-South** is traffic crossing the cluster boundary — a user's browser reaching TicketHub. On bare metal this is the part the cloud normally does for you, so we assemble it from **MetalLB + Ingress**:

![North-South traffic path](assets/diagrams/04-north-south.png)

1. **DNS** points `tickethub.com` at a MetalLB external IP (from the `10.20.0.0/24` pool).
2. **MetalLB** makes `Service type=LoadBalancer` actually work on bare metal by announcing that IP via **L2 (ARP)** or **BGP** to your router.
3. **NGINX Ingress** receives the traffic and does host/path routing (`/api → gateway`, `/ → frontend`), TLS termination, etc.
4. It forwards to the target **Service (ClusterIP)**, which lands on a healthy **Pod**.

!!! note "L2/ARP vs BGP, briefly"
    To make an external IP reachable, MetalLB must *advertise* it to the physical network.
    **L2 mode** answers **ARP** (the LAN's "who has this IP?" broadcast) from a single
    elected node — simple, but all traffic funnels through that one node. **BGP mode** peers
    with your router using the **BGP** routing protocol so several nodes serve the IP at
    once (true load-sharing). L2 for simplicity, BGP for scale.

!!! mental "Mental model — airport arrivals"
    North-South is the **arrivals hall** of an airport. **MetalLB** is the runway that
    lets planes land at all (a public gate/IP). **Ingress** is passport control and
    the signage that routes each traveler to the right terminal (service). Without
    MetalLB, planes have nowhere to land; without Ingress, travelers wander the tarmac.

### 4.4 East-West traffic — pods talking to each other

**East-West** is the far larger volume: Orders calling Inventory, everything hitting Redis. Every pod gets a **routable-within-the-cluster IP** from the Pod CIDR, and reaches others via **Service DNS**:

![East-West traffic path](assets/diagrams/04-east-west.png)

- A pod calls `inventory.tickethub.svc.cluster.local` — CoreDNS resolves it to the Inventory **ClusterIP**.
- **Cilium** (our CNI) programs the kernel (via **eBPF**) to route the packet straight to a backend pod, load-balancing across replicas — **without** the traditional `iptables` hairpin that kube-proxy uses.

### 4.5 How Cilium moves the packets (the data path)

![Cilium eBPF datapath](assets/diagrams/04-cilium-datapath.png)

Cilium attaches **eBPF programs** to kernel hooks so that routing, service load-balancing, and **NetworkPolicy enforcement** all happen in-kernel at the same layer. Benefits for TicketHub:

| Capability | Why it matters |
|------------|----------------|
| **eBPF routing** | Faster than iptables at scale; no giant rule chains |
| **kube-proxy replacement** | Cilium can *be* the service proxy — fewer moving parts |
| **NetworkPolicy (L3–L7)** | Zero-trust between services (Chapter 21) |
| **Hubble** | Live flow maps — *see* every Orders→Inventory call |

```bash
# Foreshadowing Chapter 6 — Cilium is installed with these CIDRs
cilium install \
  --set ipam.mode=cluster-pool \
  --set ipam.operator.clusterPoolIPv4PodCIDRList=10.244.0.0/16 \
  --set kubeProxyReplacement=true \
  --set hubble.relay.enabled=true --set hubble.ui.enabled=true
```

### 4.6 Cluster DNS

Inside the cluster, **CoreDNS** resolves service names. Every Service gets a stable DNS name:

```text
<service>.<namespace>.svc.cluster.local
  inventory.tickethub.svc.cluster.local  -> Inventory ClusterIP
  postgres-primary.data.svc.cluster.local -> Postgres StatefulSet pod
```

!!! warning "Bare-metal gotchas to plan for now"
    - **MetalLB L2 mode** funnels all traffic for an IP through **one** node at a time
      (failover, not load-share). Use **BGP mode** with a capable router for true
      multi-node load distribution.
    - **`hostNetwork` pods** bypass the Pod CIDR and grab node ports directly — use
      sparingly (e.g., the ingress controller) and track those ports.
    - Keep the **MetalLB pool** comfortably larger than your expected number of
      `LoadBalancer` services so you never run out of external IPs.

!!! success "Chapter 4 checklist — the network blueprint"
    - A written **IP plan**: node, MetalLB, Pod, and Service ranges that **don't overlap**.
    - **VLAN separation** of management vs application traffic.
    - **North-South** path designed: DNS → MetalLB → NGINX Ingress → Service → Pod.
    - **East-West** path understood: Pod IP + Service DNS, routed by **Cilium eBPF**.
    - **CoreDNS** naming convention known by every service.

    Part I is complete — we know **what** we're building (Ch 1) and **where** it runs
    (Ch 2–4). Part II installs Kubernetes onto this foundation.

---
