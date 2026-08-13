## <a name="ch6"></a>6. The CNI — Cilium (eBPF) + Hubble

A freshly `init`ed cluster has no pod networking until you install a **CNI (Container Network Interface)** plugin. The CNI is arguably the most consequential platform choice an architect makes — it determines how pods get IPs, how Services are load-balanced, how NetworkPolicy is enforced, and what observability you get. We chose **Cilium**.

### 6.1 What a CNI actually does

When the scheduler places a pod on a node, the kubelet calls the CNI plugin to:

1. Create the pod's network namespace and a **veth** pair.
2. Assign the pod an **IP** from the node's slice of the Pod CIDR (**IPAM**).
3. Program the **routes** so the pod can reach other pods and Services.
4. Enforce **NetworkPolicy** for traffic in/out of the pod.

Traditional CNIs (e.g., Flannel + kube-proxy) do steps 3–4 with **iptables**, which becomes a giant, slow rule-chain at scale. **Cilium uses eBPF** instead — small programs loaded into the Linux kernel.

!!! mental "Mental model — programmable kernel vs paper rulebook"
    iptables is a **paper rulebook** the kernel reads top-to-bottom for every packet —
    fine for 50 rules, painful for 50,000. **eBPF** is like **installing a custom chip**
    into the kernel's networking path that already *knows* the routing and policy
    decisions as fast hash-map lookups. Same decisions, dramatically faster, plus deep
    visibility.

### 6.2 Cilium's components

![Cilium architecture](assets/diagrams/06-cilium-arch.png)

| Component | Kind | Role |
|-----------|------|------|
| **cilium-agent** | DaemonSet (one per node) | Compiles Services + NetworkPolicy into **eBPF** on that node |
| **cilium-operator** | Deployment (one per cluster) | Cluster-wide housekeeping: IPAM, garbage collection |
| **eBPF programs** | In-kernel | The actual datapath: routing, LB, policy |

```bash
# Install with the settings that match our design (Ch 4)
cilium install --version 1.16.1 \
  --set kubeProxyReplacement=true \                 # Cilium IS the service proxy
  --set ipam.mode=cluster-pool \
  --set ipam.operator.clusterPoolIPv4PodCIDRList=10.244.0.0/16 \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true \
  --set loadBalancer.mode=dsr                        # direct server return, lower latency

cilium status --wait
cilium connectivity test                             # end-to-end self-test
```

!!! key "kube-proxy replacement is a real architectural win"
    By setting `kubeProxyReplacement=true`, Cilium removes kube-proxy entirely and
    implements `ClusterIP`/`NodePort`/`LoadBalancer` service routing in eBPF. Fewer
    components, no bloated iptables/IPVS rules, and lower latency for TicketHub's
    heavy East-West traffic (Orders↔Inventory↔Redis).

!!! note "What kube-proxy actually did"
    Classic Kubernetes ran **kube-proxy** on every node to turn a Service's virtual IP into
    real pod IPs by programming large `iptables`/IPVS rule tables — which grow slow as
    services multiply. Cilium performs the same routing in **eBPF** (fast in-kernel hash
    lookups), so `kubeProxyReplacement=true` lets us drop kube-proxy entirely: one fewer
    moving part, and lower East-West latency.

### 6.3 Why Cilium for TicketHub specifically

| Need (from Part I) | Cilium capability |
|--------------------|-------------------|
| Zero-trust between 9 services | **L3–L7 NetworkPolicy** (even HTTP-path-aware) — Chapter 21 |
| High East-West throughput | eBPF datapath, DSR load balancing |
| "Why can't Orders reach Payments?" | **Hubble** flow visibility with allow/deny verdicts |
| Fewer moving parts | kube-proxy replacement |
| Future multi-cluster | Cluster Mesh (out of scope, but available) |

### 6.4 Hubble — seeing the network

Cilium's sister project **Hubble** taps the same eBPF hooks to give you a live map of **every flow** in the cluster: source, destination, port, L7 protocol, and whether policy **allowed or denied** it.

![Hubble observability](assets/diagrams/06-hubble.png)

```bash
# Observe live flows to the Payments service, denied only
hubble observe --to-pod tickethub/payments --verdict DROPPED

# Open the graphical service map
cilium hubble ui        # port-forwards the Hubble UI
```

!!! tip "Hubble makes NetworkPolicy debuggable"
    The usual pain with NetworkPolicy is "I applied a policy and now something's
    broken, but *what*?" Hubble answers directly: it shows the **dropped** flow with
    the exact source, destination, and port, so you know precisely which rule to add.
    We'll lean on this heavily in Chapter 21.

### 6.5 Verifying pod networking

```bash
kubectl run test --image=nicolaka/netshoot -it --rm -- bash
# inside: curl inventory.tickethub.svc.cluster.local:8080/healthz
# inside: dig frontend.tickethub.svc.cluster.local
cilium status                      # agents healthy, eBPF programs loaded
cilium endpoint list               # every pod endpoint + policy state
```

!!! warning "CNI is hard to change later — choose deliberately"
    Swapping a CNI on a running production cluster is a disruptive, drain-and-migrate
    exercise. Decide up front. Cilium fits TicketHub's needs (policy depth,
    performance, observability); Flannel would be simpler but has **no NetworkPolicy**,
    which is a non-starter for a payment platform.

!!! success "Chapter 6 checklist"
    - CNI installed → all nodes **Ready**, `cilium connectivity test` passes.
    - **kube-proxy replaced** by Cilium eBPF.
    - **Hubble** enabled for flow visibility (UI + CLI).
    - Pod-to-pod and Service DNS verified from a debug pod.

---
