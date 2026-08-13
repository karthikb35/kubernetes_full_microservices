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

!!! success "Chapter 14 checklist — Part III complete"
    - Stateful workloads use **StatefulSets** with `volumeClaimTemplates` (one PVC per replica).
    - PVCs bind via `WaitForFirstConsumer` so volumes land in the pod's failure domain.
    - **RWO block** for databases; `reclaimPolicy: Retain` protects the data.
    - Passwords injected from **Secrets** (Chapter 13), not baked into images.
    - Understood: deleting a StatefulSet **keeps** its PVCs — reclaim storage deliberately.

    TicketHub is now fully containerized and deployed — stateless services, stateful data,
    config, and storage. **Part IV** makes it reliable and elastic: resource management,
    autoscaling, scheduling, and health.

---
