## <a name="ch11"></a>11. Workload Controllers — Deployments, ReplicaSets, StatefulSets & DaemonSets

A pod is the smallest unit Kubernetes runs — but you almost **never** create a bare pod. A bare pod that dies stays dead. Instead you declare a **controller** that owns pods and continuously reconciles reality toward your desired state. Choosing the *right* controller for each workload shape is a core architect decision.

### 11.1 The controller family

![Controller types](assets/diagrams/11-controller-types.png)

| Controller | Guarantees | TicketHub workloads |
|-----------|------------|---------------------|
| **Deployment** | N interchangeable replicas, rolling updates, instant rollback | frontend, gateway, users, catalog, orders, payments, notifications, search |
| **StatefulSet** | Stable identity + stable per-pod storage, ordered ops | Postgres, Kafka, Redis (Ch 14) |
| **DaemonSet** | Exactly one pod per (matching) node | cilium, node-exporter, Falco, log shipper |
| **Job / CronJob** | Run to completion, once or on schedule | DB migrations, nightly reports |

!!! mental "Mental model — cattle, pets, and sentries"
    **Deployment** pods are **cattle**: identical, numbered by chance, replaced without
    ceremony. **StatefulSet** pods are **pets**: each has a name and its own belongings
    (disk) that follow it. **DaemonSet** pods are **sentries**: one posted on every node,
    watching that node.

### 11.2 Deployments and the ReplicaSet underneath

A **Deployment** doesn't manage pods directly — it manages **ReplicaSets**. Each rollout creates a *new* ReplicaSet and gradually shifts pods to it, keeping the old one at zero for instant rollback.

![Deployment hierarchy](assets/diagrams/11-deployment-hierarchy.png)

```yaml
# repo/manifests/30-workloads/catalog-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  namespace: tickethub
spec:
  replicas: 3
  selector:
    matchLabels: { app: catalog }
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0        # never drop below desired during a rollout
      maxSurge: 1              # add one extra pod at a time
  template:
    metadata:
      labels: { app: catalog }
    spec:
      containers:
        - name: catalog
          image: registry.internal/tickethub/catalog@sha256:...  # immutable digest
          ports: [{ containerPort: 8080 }]
          resources:
            requests: { cpu: "100m", memory: 128Mi }
            limits:   { cpu: "500m", memory: 512Mi }
```

```bash
kubectl -n tickethub set image deploy/catalog catalog=...:v2   # triggers new ReplicaSet
kubectl -n tickethub rollout status deploy/catalog             # watch it converge
kubectl -n tickethub rollout undo deploy/catalog               # instant rollback
```

!!! tip "maxUnavailable: 0 for user-facing services"
    Setting `maxUnavailable: 0` with `maxSurge: 1` means Kubernetes brings up a new pod
    *before* removing an old one — zero capacity dip during deploys. Combine with
    **readiness probes** (Chapter 18) so traffic only shifts to pods that are actually up.

### 11.3 StatefulSets — when identity and storage matter

Stateless replicas are interchangeable; a database replica is **not**. `postgres-0` is the primary, has its *own* data, and must keep its name and disk across reschedules. That's a **StatefulSet**.

![StatefulSet](assets/diagrams/11-statefulset.png)

| Deployment | StatefulSet |
|-----------|-------------|
| Random pod names (`catalog-7d9f-xk2`) | Ordinal names (`postgres-0`, `-1`, `-2`) |
| Shared or no storage | One PVC **per pod**, sticks to it |
| Any order, parallel | Ordered create/scale/delete (0→1→2) |
| ClusterIP Service | Usually a **headless** Service for stable DNS |

We build these fully in Chapter 14; the point here is **controller selection**: identity + per-pod disk ⇒ StatefulSet.

### 11.4 DaemonSets — one pod per node

Some software must run on **every** node: the CNI agent, a metrics exporter, a security sensor. A **DaemonSet** guarantees exactly that, and automatically places a pod on any node that joins later.

```yaml
# repo/manifests/70-observability/node-exporter-daemonset.yaml (excerpt)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels: { app: node-exporter }
  template:
    metadata:
      labels: { app: node-exporter }
    spec:
      tolerations:                 # so it also lands on tainted data/infra nodes
        - operator: Exists
      containers:
        - name: node-exporter
          image: quay.io/prometheus/node-exporter:v1.8.0
          ports: [{ containerPort: 9100, hostPort: 9100 }]
```

!!! key "Add broad tolerations to node-wide agents"
    Because data and infra nodes are **tainted** (Chapter 3), a DaemonSet that must cover
    *all* nodes needs `tolerations: [{ operator: Exists }]`. Otherwise your metrics or
    security agent silently skips exactly the nodes you most need to watch.

### 11.5 Jobs & CronJobs — batch work

Schema migrations and scheduled reports aren't long-running services — they **finish**.

```yaml
# repo/manifests/30-workloads/db-migrate-job.yaml
apiVersion: batch/v1
kind: Job
metadata: { name: orders-db-migrate, namespace: tickethub }
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.internal/tickethub/orders-migrate@sha256:...
          command: ["/migrate", "up"]
```

Run migrations as a **Job** (often an Argo CD *PreSync* hook, Chapter 28) so schema changes land before the new app version rolls out.


### 11.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - A **ReplicaSet** is the actual controller that maintains the desired pod count — a Deployment manages ReplicaSets, not pods directly. When you do a rolling update, the Deployment creates a NEW ReplicaSet and scales it up while scaling down the old one. The old ReplicaSet (with 0 replicas) is kept as rollback history — `kubectl rollout history` lists them.
    - **DaemonSets bypass the scheduler's bin-packing** — they place exactly one pod per matching node regardless of available resources. If a DaemonSet pod's resource requests cannot fit on a node, the pod stays `Pending` on that node forever (no eviction of other pods to make room). Size DaemonSet pods conservatively.
    - **StatefulSet `podManagementPolicy: Parallel`** allows all pods to start simultaneously (faster), but the default `OrderedReady` is safer for databases that require pod-0 to be the primary before pod-1 starts replication. Never switch a Postgres StatefulSet to Parallel without understanding the startup coordination consequences.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`kubectl delete rs` on a Deployment-owned ReplicaSet**: the Deployment controller immediately re-creates the ReplicaSet. This is not a rollback — it creates a fresh RS with the same pod template. To rollback, use `kubectl rollout undo deployment/X`.
    - **StatefulSet rolling update leaves a failed pod blocking the rollout**: if pod-0 fails its readiness probe after the update, the rollout pauses — pods 1 and 2 are never updated. The rollout does not time out or auto-rollback. You must manually fix pod-0 OR run `kubectl rollout undo` to unblock.
    - **DaemonSet on tainted nodes**: a new `NoSchedule` taint on a node does not evict existing DaemonSet pods. The taint only affects newly scheduled pods. If you retaint a node, DaemonSet pods on it are unaffected until the next pod restart.

!!! question "Architect Considerations"
    1. **Deployment vs StatefulSet boundary**: the line is "does pod identity matter?" If `orders-pod-7f4d` can replace `orders-pod-a1b2` without any state transfer, use a Deployment. If each pod has a named role (Postgres primary vs standby), use a StatefulSet. The gray area is services that use external session stores (Redis) — they are truly stateless and should use Deployments.
    2. **DaemonSet for security vs performance**: Falco, node-exporter, and Cilium agents are natural DaemonSets. But a heavy DaemonSet (e.g., a 512Mi baseline logging agent) on every node burns constant cluster-wide RAM. Always benchmark DaemonSet overhead per node type before deploying.
    3. **Job completion vs Deployment for one-time tasks**: `db-migrate-job.yaml` (repo/manifests/30-workloads/) runs schema migrations as a Job. Migrations run in a Deployment would run in a loop forever. The key Job parameters: `backoffLimit: 3` (max retries), `restartPolicy: Never` (don't restart the pod on failure, create a new one instead).
    4. **CronJob concurrency policy**: `concurrencyPolicy: Forbid` means if the previous CronJob run is still running when the next trigger fires, the new run is skipped. For backup or batch jobs where overlapping runs would corrupt output, `Forbid` is the right choice; for idempotent jobs, `Allow` gives better throughput.
    5. **Pod disruption budget interaction with Deployments**: a PDB with `minAvailable: 2` on a 3-replica Deployment means a `kubectl rollout restart` will drain only one pod at a time — the rollout serializes. This is the correct behavior for zero-downtime restarts but multiplies the rollout duration by the replica count.

!!! success "Chapter 11 checklist"
    - Stateless services run as **Deployments** with `maxUnavailable: 0`, immutable image digests.
    - Databases/brokers run as **StatefulSets** (identity + per-pod storage).
    - Node-wide agents run as **DaemonSets** with `Exists` tolerations.
    - Migrations/scheduled work run as **Jobs/CronJobs**, not long-lived pods.
    - No bare pods anywhere — every pod is owned by a controller.

---
