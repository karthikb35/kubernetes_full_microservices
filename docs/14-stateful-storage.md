## <a name="ch14"></a>14. Stateful Storage — PV/PVC & StatefulSet volumeClaimTemplates

Chapter 8 built the storage *platform* (Rook-Ceph, StorageClasses). Chapter 11 introduced StatefulSets. This chapter joins them: how TicketHub's **databases and brokers** get durable, identity-bound storage that survives pod death, rescheduling, and node failure — without an operator manually creating a single volume.

### 14.1 Recap — the storage abstractions in motion

A stateless pod can lose its writable layer and nobody cares. Postgres cannot. It needs a **PersistentVolume** that outlives the pod. The workload asks with a **PVC**; the **StorageClass** provisions a **PV** dynamically (Chapter 8). For StatefulSets, we don't write the PVCs by hand at all.

!!! mental "Mental model — assigned lockers at a gym"
    A Deployment pod is a **day-pass locker** — grab any free one, empty it when you leave.
    A StatefulSet pod has an **assigned annual locker**: `postgres-0` always returns to
    locker #0 with its own contents intact, even after it goes home and comes back
    (reschedules). The locker (PVC) is bound to the member (pod ordinal), not the visit.

### 14.2 volumeClaimTemplates — one PVC per replica, automatically

The magic of a StatefulSet is `volumeClaimTemplates`: for each replica it **mints a dedicated PVC** (`data-kafka-0`, `data-kafka-1`, …), each bound to its own PV, each following its pod forever.

![volumeClaimTemplates](assets/diagrams/14-volumeclaimtemplates.png)

```yaml
# repo/manifests/20-data/kafka-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka
  namespace: data
spec:
  serviceName: kafka               # the headless Service (stable DNS)
  replicas: 3
  selector:
    matchLabels: { app: kafka }
  template:
    metadata:
      labels: { app: kafka }
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: kafka
          image: bitnami/kafka:3.7
          ports: [{ containerPort: 9092 }]
          volumeMounts:
            - name: data
              mountPath: /bitnami/kafka
          resources:
            requests: { cpu: "1", memory: 2Gi }
            limits:   { cpu: "2", memory: 4Gi }
  volumeClaimTemplates:            # <-- one PVC created PER replica
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: rook-ceph-block
        resources:
          requests:
            storage: 50Gi
```

The result:

```bash
kubectl -n data get pvc
# data-kafka-0   Bound   ...   50Gi   rook-ceph-block
# data-kafka-1   Bound   ...   50Gi   rook-ceph-block
# data-kafka-2   Bound   ...   50Gi   rook-ceph-block
```

### 14.3 How binding actually happens

Because the StorageClass uses `volumeBindingMode: WaitForFirstConsumer` (Chapter 8), the PV isn't provisioned until the pod is **scheduled** — so the volume lands in the right failure domain, next to its pod.

![PVC lifecycle](assets/diagrams/14-pvc-lifecycle.png)

The crucial property: on **reschedule** (node failure, rollout), Kubernetes re-attaches the *same* PVC to the pod with the *same* ordinal. `kafka-1` always comes back with `data-kafka-1` — identity **and** data preserved.

!!! key "Deleting a StatefulSet does NOT delete its PVCs"
    This is deliberate data-safety behavior. `kubectl delete statefulset kafka` removes
    the pods but **leaves `data-kafka-*` PVCs (and their PVs) intact**. Recreate the
    StatefulSet and it re-adopts the existing volumes. To actually reclaim storage you
    must delete the PVCs explicitly — a guardrail against accidental data loss.

### 14.4 Postgres with a primary + replicas

Postgres uses the same pattern, fronted by the headless Service from Chapter 12 so replicas find the primary at a stable address:

```yaml
# repo/manifests/20-data/postgres-statefulset.yaml (excerpt)
spec:
  serviceName: postgres
  replicas: 3
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: { name: postgres-db, key: password }   # Ch 13
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: rook-ceph-block   # reclaimPolicy: Retain (Ch 8)
        resources: { requests: { storage: 20Gi } }
```

### 14.5 Choosing access mode and reclaim policy per workload

| Workload | Access mode | StorageClass reclaim | Why |
|----------|-------------|----------------------|-----|
| Postgres / Kafka / Redis | **RWO** (block) | **Retain** | Single writer; never auto-wipe a DB |
| Shared uploads | **RWX** (CephFS) | Delete | Many pods read/write; ephemeral-ish |
| Backups / index snapshots | Object (S3) | n/a | Blob storage, lifecycle-managed |

!!! warning "Match the access mode to the engine"
    Databases demand **RWO block** — a single writer with block semantics. Putting Postgres
    on an **RWX** shared filesystem invites corruption (Chapter 8). Reserve RWX for
    genuinely concurrency-safe shared data.

### 14.6 DB Replication with CRDs — moving beyond raw StatefulSets {#146-db-replication-with-crds}

A raw StatefulSet (sections 14.2–14.4) gives Postgres stable identity and
durable storage. It does **not** give it:

- automatic **streaming replication** between primary and standbys,
- a **failover controller** that promotes a standby when the primary dies,
- a **connection pooler** to prevent connection-count exhaustion,
- **WAL archiving** for point-in-time recovery (PITR), or
- a **replication slot** lifecycle manager that prevents disk bloat.

Managing all of that by hand requires custom init-container scripts, sidecars,
and maintenance procedures — work that is better encoded as an **operator**
driven by CRDs (Chapter 25). TicketHub's `tickethub-db-operator` consumes two
new API types in the `db.tickethub.io` group.

#### 14.6.1 The two new CRDs

```yaml
# CRD registration (abbreviated) — full definition in
# repo/manifests/20-data/postgres-replication-crd.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: postgresreplicationclusters.db.tickethub.io
spec:
  group: db.tickethub.io
  names: { kind: PostgresReplicationCluster, plural: postgresreplicationclusters, shortNames: [pgrc] }
  scope: Namespaced
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                instances:          { type: integer, minimum: 1, maximum: 9 }
                postgresVersion:    { type: integer, enum: [14,15,16,17], default: 16 }
                replication:
                  type: object
                  properties:
                    synchronousMode: { type: string, enum: [none, first, quorum] }
                    hotStandby:      { type: boolean, default: true }
                    walLevel:        { type: string,  enum: [replica, logical] }
                walArchive:
                  type: object
                  properties:
                    enabled:     { type: boolean }
                    destination: { type: string }
                failover:
                  type: object
                  properties:
                    automaticFailover: { type: boolean, default: true }
                    promotionTimeout:  { type: integer, default: 60 }
                connectionPooler:
                  type: object
                  properties:
                    enabled:    { type: boolean }
                    poolMode:   { type: string, enum: [session, transaction, statement] }
                    maxClientConn: { type: integer }
                storage:
                  type: object
                  required: [size, storageClass]
                  properties:
                    size:         { type: string }
                    storageClass: { type: string }
```

The second CRD, `ReplicationSlot`, models an individual physical or logical
replication slot with a retention policy:

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: replicationslots.db.tickethub.io
spec:
  group: db.tickethub.io
  names: { kind: ReplicationSlot, plural: replicationslots, shortNames: [rslot] }
  scope: Namespaced
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required: [clusterRef, type]
              properties:
                clusterRef: { type: string }
                type:       { type: string, enum: [physical, logical] }
                plugin:     { type: string }        # pgoutput | wal2json
                retentionPolicy:
                  type: object
                  properties:
                    maxWalSize:      { type: string, default: 2Gi }
                    inactiveTimeout: { type: string, default: 24h }
```

!!! key "Why manage replication slots as CRs?"
    An inactive logical slot that accumulates WAL without a consumer will
    silently fill the disk and crash the primary. Declaring slots as
    `ReplicationSlot` CRs gives the operator **ownership** — it can monitor
    `pg_replication_slots`, fire a Kubernetes `Event`, and drop the slot before
    it becomes critical.

#### 14.6.2 The TicketHub PostgresReplicationCluster CR

```yaml
# repo/manifests/20-data/postgres-replication-crd.yaml (CR excerpt)
apiVersion: db.tickethub.io/v1alpha1
kind: PostgresReplicationCluster
metadata:
  name: tickethub-postgres
  namespace: data
spec:
  instances: 3                  # postgres-0 (primary) + 2 hot standbys
  postgresVersion: 16
  replication:
    synchronousMode: quorum     # ack after 1 standby flushes → RPO = 0
    synchronousStandbys: 1
    walLevel: replica
    hotStandby: true            # standbys serve read-only queries
  walArchive:
    enabled: true
    destination: s3://tickethub-wal/postgres
    credentialsSecret: ceph-s3-creds
    retentionDays: 7
  failover:
    automaticFailover: true
    promotionTimeout: 60
    primaryUpdateStrategy: RollingUpdate
  connectionPooler:
    enabled: true
    poolMode: transaction       # connection returned after each txn
    maxClientConn: 400
    defaultPoolSize: 25
  storage:
    size: 20Gi
    storageClass: rook-ceph-block
    walStorage:
      size: 10Gi                # separate disk prevents data-PVC WAL bloat
      storageClass: rook-ceph-block
  monitoring:
    enablePodMonitor: true
  bootstrap:
    method: initdb
    secretName: postgres-db
```

After `kubectl apply`, the operator creates a StatefulSet, two Services
(read-write → primary, read-only → standbys), a PgBouncer Deployment, and a
PodMonitor. The raw `postgres-statefulset.yaml` remains the conceptual
teaching scaffold; the `PostgresReplicationCluster` CR is what production runs.

#### 14.6.3 Streaming replication architecture

![Postgres replication cluster](assets/diagrams/14-db-replication-arch.png)

The three pods run the same `postgres:16` image. The operator:

1. Labels `postgres-0` as `role=primary` on bootstrap.
2. Configures `postgres-1` and `postgres-2` with `primary_conninfo` pointing
   at the primary's stable headless DNS name (`postgres-0.postgres.data`).
3. Creates **physical replication slots** on the primary for each standby,
   ensuring the primary keeps enough WAL for lagging standbys.
4. Starts the `pg_basebackup` in each standby init-container to clone data.

#### 14.6.4 WAL streaming — how data flows

![WAL streaming sequence](assets/diagrams/14-streaming-replication.png)

Every write on the primary appends to the **Write-Ahead Log (WAL)**. A **WAL
sender** process streams these bytes to each standby's **WAL receiver**, which
writes them to its own WAL file. A **startup process** on the standby replays
the WAL continuously, keeping the standby within milliseconds of the primary.

With `synchronousMode: quorum` the primary delays the `COMMIT` response until
at least one standby has *flushed* (written to disk) the relevant WAL. This
gives **zero RPO** for any single-standby loss — no committed transaction can
be lost even if the primary dies immediately after the ack.

| Mode | Behaviour | Trade-off |
|---|---|---|
| `none` | Async — commit before standby acks | Maximum throughput; seconds of RPO possible |
| `first` | Wait for first standby to flush | < 1ms extra latency; RPO = 0 for 1 loss |
| `quorum` | Wait for quorum of standbys | Highest durability; best for financial data |

#### 14.6.5 Automatic failover

If `automaticFailover: true` and the primary is unreachable for
`promotionTimeout` seconds, the operator:

1. Queries `pg_stat_replication` on each standby to find the least-lagging one.
2. Runs `SELECT pg_promote()` on the chosen standby.
3. Re-labels it `role=primary`; the **rw-pool Service** endpoint flips within
   one kube-proxy sync cycle (< 1 s).
4. Configures remaining standbys to follow the new primary via `pg_rewind`.
5. Writes `status.currentPrimary` and emits a `Normal/Failover` Event.

The old primary, if it recovers, is automatically demoted and rejoins as a
standby — no manual intervention needed.

#### 14.6.6 Connection pooling

With `connectionPooler.enabled: true` the operator deploys **PgBouncer** as a
2-replica stateless Deployment in front of Postgres. In `transaction` pool mode
each server connection is held only for the duration of a transaction and then
returned to the pool — allowing hundreds of app threads to share a small number
of actual Postgres connections:

```
400 client conns (PgBouncer) → 25 server conns (Postgres primary)
```

Without a pooler, each microservice replica opens its own persistent
connections. With 30+ `orders` pods the raw connection count can push Postgres
past `max_connections` and cause `FATAL: sorry, too many clients already`.

```bash
# Inspect pool state
kubectl -n data exec deploy/pgbouncer -- psql -p 6432 pgbouncer -c "SHOW POOLS;"
```

!!! success "Chapter 14 checklist — Part III complete"
    - Stateful workloads use **StatefulSets** with `volumeClaimTemplates` (one PVC per replica).
    - PVCs bind via `WaitForFirstConsumer` so volumes land in the pod's failure domain.
    - **RWO block** for databases; `reclaimPolicy: Retain` protects the data.
    - Passwords injected from **Secrets** (Chapter 13), not baked into images.
    - Understood: deleting a StatefulSet **keeps** its PVCs — reclaim storage deliberately.
    - Production Postgres uses **CRDs** (`PostgresReplicationCluster`, `ReplicationSlot`)
      to declare streaming replication, failover, pooling, and WAL archiving declaratively.
    - `synchronousMode: quorum` achieves **RPO = 0** for single-standby loss.
    - Logical `ReplicationSlot` CRs carry a `retentionPolicy` to prevent WAL bloat.

    TicketHub is now fully containerized and deployed — stateless services, stateful data,
    config, and storage. **Part IV** makes it reliable and elastic: resource management,
    autoscaling, scheduling, and health.

---
