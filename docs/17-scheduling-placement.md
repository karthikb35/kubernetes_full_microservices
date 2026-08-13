## <a name="ch17"></a>17. Scheduling & Placement — PriorityClass, Affinity, Taints, Topology Spread & PDB

Autoscaling decides *how many* pods; **scheduling** decides *where* they run. Left alone, the scheduler does a good job — but a production architect steers it deliberately: keep databases on data nodes, spread replicas across racks so one failure can't take a service down, and make sure revenue-critical pods win when the cluster is full.

### 17.1 How the scheduler decides

![Scheduling cycle](assets/diagrams/17-scheduling-cycle.png)

For every Pending pod the scheduler runs two phases:

1. **Filter (predicates)** — eliminate nodes that *can't* run it: not enough free requests, taint not tolerated, `nodeSelector`/affinity mismatch, volume zone conflict.
2. **Score (priorities)** — rank the survivors: spread, least-loaded, affinity weights. Highest score gets the pod (**bind**).

!!! mental "Mental model — seating guests at a wedding"
    **Filtering** removes impossible tables (allergy conflicts, no free seats).
    **Scoring** picks the *best* remaining table (near friends, away from the loud
    speakers). The scheduler seats one guest (pod) at a time onto the best feasible node.

### 17.2 Taints & tolerations — repelling pods

A **taint** on a node repels pods that don't explicitly **tolerate** it. This is how the data and infra pools (Chapter 3) stay reserved.

![Affinity and taints](assets/diagrams/17-affinity-taints.png)

```yaml
# node carries: kubectl taint nodes worker-data-1 data=true:NoSchedule
tolerations:
  - key: "data"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"      # only tolerating pods (Postgres, Kafka) may land
```

### 17.3 Affinity & anti-affinity — attracting and separating

Where taints *repel*, **affinity** *attracts* pods to labels, and **anti-affinity** keeps replicas apart.

```yaml
affinity:
  nodeAffinity:                                  # run only on data nodes
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - { key: pool, operator: In, values: [data] }
  podAntiAffinity:                               # spread replicas across hosts
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels: { app: orders }
          topologyKey: kubernetes.io/hostname
```

!!! key "Anti-affinity is what makes replicas actually redundant"
    Three `orders` replicas on the **same node** give you zero resilience — one node
    failure kills all three. `podAntiAffinity` on `topologyKey: hostname` forces them onto
    **different nodes**, so the whole point of replication (surviving a node loss) holds.

### 17.4 Topology spread & Pod Disruption Budgets

**Topology spread constraints** balance replicas evenly across failure domains (zones/racks); a **PodDisruptionBudget (PDB)** guarantees a minimum stay running during *voluntary* disruptions (node drains, upgrades).

![Topology spread and PDB](assets/diagrams/17-topology-spread.png)

```yaml
# spread constraint in the pod spec
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector: { matchLabels: { app: catalog } }
---
# repo/manifests/50-scaling/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: catalog, namespace: tickethub }
spec:
  minAvailable: 2                        # never let a drain drop below 2
  selector: { matchLabels: { app: catalog } }
```

!!! warning "On bare metal, the zone label must exist or the spread is a silent no-op"
    `topology.kubernetes.io/zone` is only meaningful if the nodes actually carry it. A
    cloud sets it automatically; **your bare-metal cluster does not** — you label nodes by
    rack yourself (Chapter 3). If the label is missing, every node looks like one giant
    zone, `maxSkew` is trivially satisfied, and all replicas can pile into a single rack
    while the constraint reports success. With `whenUnsatisfiable: ScheduleAnyway` it fails
    *open* (schedules anyway); use `DoNotSchedule` only once you're sure the labels exist.

!!! warning "Without a PDB, a node drain can take your whole service down"
    `kubectl drain` (upgrades, Chapter 27) evicts *all* pods on a node at once. If two of
    your three replicas happened to share that node and there's no PDB, the service can
    briefly hit zero healthy pods. A PDB makes the drain **wait** until replacements are
    Ready elsewhere. Every user-facing service needs one.

### 17.5 PriorityClass & preemption

When the cluster is full, **PriorityClass** decides who wins — and lets high-priority pods **preempt** (evict) lower-priority ones to make room.

![PriorityClass](assets/diagrams/17-priorityclass.png)

```yaml
# repo/manifests/50-scaling/priorityclasses.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: payments-critical }
value: 100000
globalDefault: false
description: "Revenue-critical services; may preempt batch work."
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: batch-low }
value: 100
description: "Reports/reindex; first to be preempted."
```

!!! success "Chapter 17 checklist"
    - Data/infra pools **tainted**; only matching workloads **tolerate** them.
    - Replicas use **podAntiAffinity** + **topologySpreadConstraints** across nodes/zones.
    - Every user-facing service has a **PodDisruptionBudget**.
    - **PriorityClasses** protect revenue-critical pods and let them preempt batch work.
    - Placement is deliberate, not accidental — verified with `kubectl get pods -o wide`.

---
