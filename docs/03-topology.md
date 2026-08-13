## <a name="ch3"></a>3. Cluster Topology — Control Plane & Worker Node Design

We have 12 VMs. Now we decide **which VM does what**. The topology of a cluster — how many control-plane nodes, how workers are grouped — determines its availability, its blast radius, and how cleanly workloads are isolated.

### 3.1 The full TicketHub topology

![Cluster topology](assets/diagrams/03-cluster-topology.png)

**12 nodes total**, organized as:

| Group | Count | Role | Node labels / taints |
|-------|-------|------|----------------------|
| **Control plane** | 3 | apiserver, etcd, scheduler, controller-manager | control-plane role — auto-tainted `NoSchedule` |
| **General workers** | 4 | Stateless services (UI, gateway, orders, ...) | `pool=general` |
| **Data workers** | 3 | Postgres, Kafka, Redis, Ceph OSDs | `pool=data`, taint `data=true:NoSchedule` |
| **Infra/edge workers** | 2 | Ingress, Prometheus, Grafana, Loki | `pool=infra`, taint `infra=true:NoSchedule` |

!!! mental "Mental model — brain, hands, vaults, doors"
    - **Control plane = the brain.** It makes decisions but runs no app workloads.
    - **General workers = the hands.** They do the everyday stateless work.
    - **Data workers = the vaults.** Guarded (tainted), they hold precious state on
      fast local disks.
    - **Infra workers = the doors & cameras.** Ingress (the doors) and monitoring
      (the cameras) live here, isolated from noisy app pods.

### 3.2 The control plane — what runs on it

Each control-plane node runs the components that *are* Kubernetes:

| Component | Role | Notes |
|-----------|------|-------|
| **kube-apiserver** | The single front door; all reads/writes go through it | Stateless → run 3, load-balanced |
| **etcd** | The cluster's database (all state) | **Quorum-based**, needs odd count |
| **kube-scheduler** | Assigns pods to nodes | One active (leader-elected) |
| **kube-controller-manager** | Runs control loops (Deployments, etc.) | One active (leader-elected) |

![HA control plane](assets/diagrams/03-control-plane-ha.png)

!!! key "Why 3 control-plane nodes, and why ODD"
    etcd uses the **Raft** consensus protocol, which needs a **majority (quorum)** to
    commit writes. With **3** members, quorum is 2 — the cluster survives **1** node
    failure. With **5**, it survives 2. An **even** number is pointless: 4 members
    still only tolerate 1 failure (quorum 3) while costing more coordination. **Rule:
    always 3 or 5, never 2 or 4.**

An external **virtual IP** (keepalived) fronts the three API servers via **HAProxy**, so `kubectl` and kubelets talk to one stable `:6443` endpoint regardless of which control-plane node is healthy.

```text
# /etc/haproxy/haproxy.cfg (on the load-balancer VIP nodes)
frontend k8s-api
    bind *:6443
    mode tcp
    default_backend k8s-cp
backend k8s-cp
    mode tcp
    balance roundrobin
    option tcp-check
    server cp-1 10.10.0.11:6443 check
    server cp-2 10.10.0.12:6443 check
    server cp-3 10.10.0.13:6443 check
```

!!! note "VIP, keepalived and Raft — the three HA words here"
    A **VIP (virtual IP)** is a single floating address clients always use. **keepalived**
    (via the VRRP protocol) moves it to a healthy load-balancer node if one dies, so the
    `:6443` endpoint never disappears. Behind it, etcd keeps its three copies in agreement
    with the **Raft** consensus protocol — an elected leader plus a majority **quorum** —
    which is exactly why the member count must be odd (see Glossary, Appendix A).

!!! warning "Control-plane nodes are tainted for a reason"
    kubeadm automatically taints control-plane nodes with
    `node-role.kubernetes.io/control-plane:NoSchedule` so **app pods never land on
    them**. Keep it that way in production — a runaway app pod must never compete with
    etcd for CPU or disk. (On a tiny dev cluster you might remove the taint; never in
    prod.)

### 3.3 Worker node pools — labels and taints

We don't want a batch Kafka rebalance stealing CPU from the Ingress controller, or a stateless UI pod landing on a precious NVMe data node. **Node pools** solve this using two primitives:

![Node pools](assets/diagrams/03-node-pools.png)

- **Labels** — attract pods (`nodeSelector`/affinity says "put me on `pool=data`").
- **Taints** — repel pods (`data=true:NoSchedule` says "only pods that *tolerate* this may land here").

```bash
# Label and taint the data pool
kubectl label node worker-data-1 worker-data-2 worker-data-3 pool=data
kubectl taint node worker-data-1 worker-data-2 worker-data-3 data=true:NoSchedule

# Label and taint the infra pool
kubectl label node worker-infra-1 worker-infra-2 pool=infra
kubectl taint node worker-infra-1 worker-infra-2 infra=true:NoSchedule
```

A pod that wants a data node must **both** select the label **and** tolerate the taint (full example in Chapter 17):

```yaml
    nodeSelector:
      pool: data
    tolerations:
      - key: data
        operator: Equal
        value: "true"
        effect: NoSchedule
```

!!! tip "Labels attract, taints repel — you usually need both"
    A label alone doesn't stop *other* pods from landing on the node. A taint alone
    doesn't guide *your* pod to it. The combination — **label + nodeSelector** to
    attract the right pods and **taint + toleration** to exclude everyone else —
    gives clean, dedicated pools.

**Failure domains — zone labels on bare metal.** `pool` labels say *what kind* of node; **zone** labels say *which independent failure domain* it lives in — a rack, a power feed, a top-of-rack switch. On a cloud, the provider sets `topology.kubernetes.io/zone` for you. **On bare metal nobody does — you must label the nodes yourself**, or the spread constraints in Chapter 17 have nothing to spread across. Map each node to its physical rack:

```bash
# Standard well-known key; value = your real failure domain (rack / power feed).
kubectl label node worker-gen-1 worker-data-1 worker-infra-1 topology.kubernetes.io/zone=rack-a
kubectl label node worker-gen-2 worker-data-2 worker-infra-2 topology.kubernetes.io/zone=rack-b
kubectl label node worker-gen-3 worker-gen-4  worker-data-3  topology.kubernetes.io/zone=rack-c
```

Now a stateful set spread `topology.kubernetes.io/zone` puts one replica per rack, so losing a rack (power or switch) never takes out a quorum. Keep the mapping honest: two "zones" sharing one PDU are not independent failure domains.

### 3.4 Sizing the control plane vs workers

| Concern | Control plane | Workers |
|---------|---------------|---------|
| Scales with | Cluster size (nodes, objects, API QPS) | Workload demand |
| Bottleneck | etcd disk latency, apiserver CPU | Pod CPU/memory |
| HA strategy | 3–5 members, spread across hosts | Many nodes, autoscale |
| Grows by | Vertical (bigger CP nodes) | Horizontal (more workers) |

!!! note "Rule of thumb for control-plane sizing"
    Up to ~50 nodes / a few thousand pods, 3 control-plane nodes at 4 vCPU / 8–16 GB
    are plenty. Past that, scale etcd to faster disks and more RAM before adding a
    4th/5th member. TicketHub at 12 nodes is comfortably in the small-cluster range.

!!! success "Chapter 3 checklist"
    - **3 control-plane** nodes (odd, HA), spread across physical hosts, **tainted**.
    - An external **VIP + HAProxy** fronting the API servers.
    - Worker **pools** (general / data / infra) defined with **labels + taints**.
    - Nodes labeled with **`topology.kubernetes.io/zone`** by physical rack (bare metal has no auto-zoning).
    - Sizing plan: control plane scales **up**, workers scale **out**.

    Next: the **network** that stitches these nodes — and their pods — together.

---
