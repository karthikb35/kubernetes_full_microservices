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
| MetalLB address pool | `10.20.0.100–200` | Gateway + any LB services |
| Pod CIDR | `10.244.0.0/16` | `kubeadm --pod-network-cidr` |
| Service CIDR | `10.96.0.0/12` | `kubeadm --service-cidr` (default) |

!!! note "VLAN separation"
    Put **management** traffic (VLAN 10) and **application/LB** traffic (VLAN 20) on
    separate VLANs. You don't want user traffic hitting the LoadBalancer pool to share
    a broadcast domain with etcd/SSH management. This is basic data-center hygiene that
    also limits blast radius.

### 4.3 North-South traffic — getting users *into* the cluster

**North-South** is traffic crossing the cluster boundary — a user's browser reaching TicketHub. On bare metal this is the part the cloud normally does for you, so we assemble it from **MetalLB + the Gateway API**:

![North-South traffic path](assets/diagrams/04-north-south.png)

1. **DNS** points `tickethub.com` at a MetalLB external IP (from the `10.20.0.0/24` pool).
2. **MetalLB** makes `Service type=LoadBalancer` actually work on bare metal by announcing that IP via **L2 (ARP)** or **BGP** to your router.
3. The **Gateway** (Cilium's Gateway API implementation) receives the traffic and does host/path routing (`/api → gateway`, `/ → frontend`), TLS termination, etc.
4. It forwards to the target **Service (ClusterIP)**, which lands on a healthy **Pod**.

!!! note "L2/ARP vs BGP, briefly"
    To make an external IP reachable, MetalLB must *advertise* it to the physical network.
    **L2 mode** answers **ARP** (the LAN's "who has this IP?" broadcast) from a single
    elected node — simple, but all traffic funnels through that one node. **BGP mode** peers
    with your router using the **BGP** routing protocol so several nodes serve the IP at
    once (true load-sharing). L2 for simplicity, BGP for scale.

!!! mental "Mental model — airport arrivals"
    North-South is the **arrivals hall** of an airport. **MetalLB** is the runway that
    lets planes land at all (a public gate/IP). The **Gateway** is passport control and
    the signage that routes each traveler to the right terminal (service). Without
    MetalLB, planes have nowhere to land; without the Gateway, travelers wander the tarmac.

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
      sparingly (e.g., the edge Gateway data plane) and track those ports.
    - Keep the **MetalLB pool** comfortably larger than your expected number of
      `LoadBalancer` services so you never run out of external IPs.


### 4.7 North-South deep dive — the full packet journey

The earlier sections told you *what* the North-South components are. This section
follows **one HTTP request** from a user's browser all the way to a pod, **layer by
layer**, so you can debug it when it breaks. We build up from first principles:
what a LoadBalancer even is, what MetalLB actually does to the packets, and where the
Gateway fits.

#### 4.7.1 The players are all just pods on your nodes

Nothing here is a magic appliance. Every "component" is software running on your VMs:

| Component | What it really is | Where it runs | Network layer it acts on |
|-----------|-------------------|---------------|--------------------------|
| **MetalLB `controller`** | 1 pod — allocates external IPs | any node | control-plane only (no data) |
| **MetalLB `speaker`** | DaemonSet — 1 pod per node, on host network | every node | **L2 (ARP)** / **L3 (BGP)** |
| **Gateway (Envoy)** | reverse-proxy pods | infra nodes | **L7 (HTTP/TLS)** |
| **kube-proxy replacement** | Cilium eBPF in the kernel | every node | **L3/L4** |
| **CoreDNS** | DNS server pods | any node | **L7 (DNS)** |

!!! key "The one-line mental model"
    **MetalLB gets the packet onto a node. The Gateway decides which app gets it.
    Cilium picks the healthy pod.** Three different jobs, three different layers —
    people fail to debug North-South because they blur them together.

#### 4.7.2 What a `LoadBalancer` Service actually is

In the cloud, this tiny YAML:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: tickethub-gateway
spec:
  type: LoadBalancer          # <-- the magic word
  selector:
    app: gateway
  ports:
    - port: 443
      targetPort: 8443
```

makes the cloud provider provision a **real external load balancer** and write its
public IP back into `.status.loadBalancer.ingress[0].ip`. On **bare metal there is no
cloud controller**, so that field stays empty forever:

```text
$ kubectl get svc tickethub-gateway
NAME                TYPE           EXTERNAL-IP     PORT(S)
tickethub-gateway   LoadBalancer   <pending>       443:31734/TCP   # stuck!
```

**MetalLB is the missing cloud controller.** It watches for `type: LoadBalancer`
Services and does the two things the cloud used to do: (1) hand out an IP, and
(2) make the physical network deliver that IP to a node.

#### 4.7.3 What MetalLB does, split into its two halves

![MetalLB split into its control-plane (controller) and data-plane (speaker) jobs](assets/diagrams/04-ns-metallb-controller-speaker.png)

The configuration objects that drive this:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: tickethub-pool
  namespace: metallb-system
spec:
  addresses:
    - 10.20.0.100-10.20.0.200      # the pool from your IP plan
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement              # or BGPAdvertisement for scale
metadata:
  name: tickethub-l2
  namespace: metallb-system
spec:
  ipAddressPools:
    - tickethub-pool
```

!!! note "'External IP' is a floating IP, not a NIC address"
    `10.20.0.100` is **not** configured on any server's network card. It is a virtual
    address that a speaker *claims* on behalf of the cluster. That is why a node can
    "own" it one second and hand it to another node the next — nothing is reconfigured
    on the NIC, only *who answers for it* changes.

#### 4.7.4 The worked example — one request, every hop

Scenario: a user opens `https://tickethub.com/api/orders`. Concrete addresses:

| Thing | Address |
|-------|---------|
| User's laptop | `10.0.5.55` (office LAN) |
| DNS answer for `tickethub.com` | `10.20.0.100` (MetalLB) |
| Node that wins the ARP election | `worker-infra-1` = `10.10.0.41`, MAC `aa:bb:cc:00:00:41` |
| Gateway (Envoy) pod | `10.244.41.7` on `worker-infra-1` |
| `api` Service ClusterIP | `10.96.45.12:80` |
| Chosen `api` pod | `10.244.22.9` on `worker-gen-2` |

![North-South packet journey: DNS, ARP, TCP, TLS, HTTP routing, ClusterIP to pod](assets/diagrams/04-ns-packet-journey.png)

Reading the diagram as three phases:

1. **L2/L3 — "get onto a node" (MetalLB's whole job).** DNS returns the floating IP.
   The laptop ARPs for it; the elected speaker on `worker-infra-1` answers with that
   node's MAC, so the switch delivers the TCP SYN to that node's real NIC. MetalLB is
   now **done** — it never looks at TLS or HTTP.
2. **L7 — "which app?" (the Gateway).** Envoy terminates TLS (it holds the certificate,
   so backend pods don't have to), reads `Host` + path, and matches an `HTTPRoute`
   (`/api/* → api`, `/ → frontend`).
3. **L3/L4 — "which pod?" (Cilium).** The Gateway opens a connection to the `api`
   **ClusterIP**; Cilium's eBPF rewrites the destination to a specific healthy pod IP
   and load-balances across replicas.

!!! example "Why the Gateway holds the public-facing IP (your recurring question)"
    The **Gateway pod** keeps its private pod IP (`10.244.41.7`). It is only
    *reachable from outside* because its **`LoadBalancer` Service** was given
    `10.20.0.100` by MetalLB. So "the Gateway is public-facing" really means *the
    Service in front of the Gateway holds the external IP*. Your backend `api` and
    `frontend` pods never get an external IP at all — exactly the one-front-door design
    you expected.

#### 4.7.5 L2 (ARP) mode vs BGP mode, visually

**L2 mode** — one node owns the IP at a time (failover, not load-share):

![L2 mode: one elected leader node answers ARP; the others stay on standby](assets/diagrams/04-ns-l2-mode.png)

**BGP mode** — the router learns the route from many nodes and ECMP-balances across them:

![BGP mode: the router ECMP-balances the external IP across several nodes at once](assets/diagrams/04-ns-bgp-mode.png)

!!! warning "L2 failover has a short blackhole"
    When the L2 leader node dies, another speaker must win the election and send a
    **gratuitous ARP** to re-point the switch. Until switch/neighbor ARP caches update
    (seconds), traffic to that IP is dropped. BGP reconverges faster and keeps serving
    from the surviving next-hops — the scale/HA reason to graduate from L2 to BGP.

### 4.8 East-West deep dive — pod-to-pod packet journey

North-South was the *arrivals hall*; **East-West is the far larger internal volume** —
Orders calling Inventory, everything hitting Redis. There is **no MetalLB and no
Gateway** here: it is pod → Service DNS → pod, moved entirely by **Cilium's eBPF**.

#### 4.8.1 A ClusterIP is a *virtual* address

`inventory`'s ClusterIP `10.96.45.12` exists on **no NIC anywhere**. It is a kernel-level
rule. When any pod sends a packet to it, Cilium's eBPF program rewrites the destination
to a **real pod IP** before the packet ever leaves the sending node. There is no proxy
hop, no `iptables` chain to walk — the translation happens inline in the kernel.

![East-West ClusterIP resolution and eBPF load-balancing to a backend pod](assets/diagrams/04-ew-clusterip.png)

#### 4.8.2 The worked example — Orders → Inventory, every hop

| Thing | Address |
|-------|---------|
| Caller: `orders` pod | `10.244.22.9` on `worker-gen-2` (`10.10.0.22`) |
| DNS name called | `inventory.tickethub.svc.cluster.local` |
| CoreDNS | `10.96.0.10` |
| `inventory` ClusterIP | `10.96.45.12:80` |
| Chosen backend | `inventory` pod `10.244.31.4` on `worker-gen-3` (`10.10.0.23`) |

![East-West packet journey: Orders to Inventory across nodes via Cilium eBPF](assets/diagrams/04-ew-packet-journey.png)

#### 4.8.3 Same-node vs cross-node — the two cases

![East-West same-node fast path versus cross-node VXLAN/Geneve tunnel](assets/diagrams/04-ew-same-vs-cross-node.png)

- **Same node:** the packet never touches the wire. eBPF hands it straight from the
  caller's veth to the callee's veth — microseconds, no encapsulation.
- **Cross node:** eBPF picks a backend on another node, encapsulates the pod-to-pod
  packet inside a **VXLAN/Geneve tunnel** addressed node-IP → node-IP
  (`10.10.0.22 → 10.10.0.23`), and the receiving node decapsulates and delivers it.
  This is why node-to-node firewall rules must permit the tunnel between all nodes.

!!! key "Why this is faster than classic kube-proxy"
    Legacy `kube-proxy` programs a long `iptables` chain per Service; every new
    connection walks rules linearly and scales poorly. Cilium replaces that with an
    **eBPF hash-table lookup** in the kernel — O(1) regardless of Service count — and
    can do **DSR** (direct server return) so replies skip the ingress node entirely.

!!! mental "Mental model — internal phone directory"
    East-West is a company's **internal phone system**. **CoreDNS** is the directory
    ("what's Inventory's extension?" → the ClusterIP). **Cilium eBPF** is the switchboard
    that instantly connects you to whichever Inventory desk is free — you dial one
    stable extension and never care which physical desk answers.

!!! warning "East-West gotchas"
    - **A ClusterIP never leaves the cluster.** Trying to curl `10.96.45.12` from your
      laptop will always fail — it is only meaningful inside a node's kernel.
    - **Long-lived connections don't rebalance.** eBPF load-balances *per connection*.
      A persistent gRPC/HTTP2 stream to a ClusterIP sticks to one backend pod until it
      closes — scale-outs won't relieve a hot stream until clients reconnect.
    - **DNS TTLs bite.** Some runtimes cache the ClusterIP; if a Service is recreated
      with a new ClusterIP, cached callers break until they re-resolve.

### 4.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - Pod CIDRs (`10.244.0.0/16`) and Service CIDRs (`10.96.0.0/12`) must **never overlap** with each other or with the node network (`10.10.0.0/16`). Cilium allocates a `/24` per node from the pod CIDR — with `/16` you can have up to 256 nodes before you need a larger CIDR (plan for growth from day one).
    - **DNS round-robin for Services is not load balancing** — it is address discovery. Cilium's eBPF does the actual per-connection load balancing at the kernel level, not at the DNS layer. This means long-lived gRPC streams to a Service IP may stay on a single backend pod until the connection is closed.
    - Node-to-node traffic uses the **node network CIDR** (`10.10.0.0/16`), not the pod CIDR. Firewall rules between nodes must allow the full pod CIDR range (for pod-to-pod across nodes) AND the Service CIDR (for return traffic through ClusterIP virtual IPs).

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Picking a pod CIDR that overlaps with a future on-prem subnet**: once a cluster is bootstrapped you cannot change the pod or service CIDRs without rebuilding. Reserve a block of RFC 1918 address space (e.g., `100.64.0.0/10`, CGNAT range) that will never appear in your corporate network.
    - **kube-dns / CoreDNS hardcoded to `10.96.0.10`**: if you choose a non-standard service CIDR, the CoreDNS ClusterIP will be different — update all references, including the kubelet `--cluster-dns` flag in the kubeadm config, or DNS resolution fails cluster-wide.
    - **MetalLB pool overlapping with node IPs**: MetalLB hands out IPs from `10.10.0.200-250` as LoadBalancer Service IPs. If a new server is assigned an IP in that range, ARP conflicts will cause intermittent routing failures. Document the split in your IP address management (IPAM) system and enforce it.

!!! question "Architect Considerations"
    1. **Address space future-proofing**: `10.244.0.0/16` gives 65,536 pod IPs. With 256 nodes × 110 pods each = 28,160 pods max. A `/15` gives twice the room; a `/14` four times. Choose based on your 3-year node growth forecast, not your current node count.
    2. **East-West encryption**: should all pod-to-pod traffic be encrypted (WireGuard overlay in Cilium) or only traffic crossing a trust boundary? Encryption adds ~5% CPU overhead. For TicketHub's on-prem cluster where physical network access is controlled, selective encryption (gateway ↔ payments) may suffice.
    3. **Egress NAT design**: pods use the node IP as the SNAT address for outbound traffic. If Payments calls Stripe from any of 9 worker IPs, Stripe must whitelist all 9. Consider a dedicated egress IP (Cilium EgressGateway) for external API calls from specific namespaces.
    4. **IPv6 dual-stack readiness**: Cilium supports dual-stack. If your data center is moving toward IPv6, plan the pod and service CIDRs to include `fd00::/112` ranges from the start — retrofitting IPv6 post-launch is expensive.
    5. **BGP vs ARP for MetalLB**: `L2 ARP` mode is simpler but has a single-node failure window (the node holding the ARP entry). `BGP` mode distributes the announcement but requires a BGP router in your rack. Choose based on your network team's capabilities.

!!! success "Chapter 4 checklist — the network blueprint"
    - A written **IP plan**: node, MetalLB, Pod, and Service ranges that **don't overlap**.
    - **VLAN separation** of management vs application traffic.
    - **North-South** path designed: DNS → MetalLB → Cilium Gateway (Gateway API) → Service → Pod.
    - **East-West** path understood: Pod IP + Service DNS, routed by **Cilium eBPF**.
    - **CoreDNS** naming convention known by every service.

    Part I is complete — we know **what** we're building (Ch 1) and **where** it runs
    (Ch 2–4). Part II installs Kubernetes onto this foundation.

---
