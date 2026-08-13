## <a name="ch8"></a>8. Storage — Rook-Ceph, StorageClasses & Dynamic PV/PVC

TicketHub's databases, Kafka logs, uploaded assets, and backups all need **durable storage that survives pod rescheduling**. On bare metal there's no cloud disk service, so we run our own distributed storage: **Ceph**, operated by **Rook**. This chapter also introduces the core Kubernetes storage abstractions — **PV, PVC, StorageClass** — that every stateful workload depends on.

### 8.1 The storage abstractions (from basics)

Kubernetes deliberately separates **what a workload wants** from **how storage is provided**:

| Object | Analogy | Who creates it |
|--------|---------|----------------|
| **PersistentVolumeClaim (PVC)** | A **request**: "I need 5Gi, read-write-once" | App developer |
| **StorageClass (SC)** | A **catalog entry**: "gold = Ceph RBD, SSD" | Cluster architect |
| **PersistentVolume (PV)** | The **actual volume** provisioned | Auto-created by the provisioner |

With **dynamic provisioning**, the developer only writes a PVC referencing a StorageClass; the PV is created automatically. No manual disk wrangling.

![Dynamic storage provisioning](assets/diagrams/08-storage-provisioning.png)

!!! mental "Mental model — ordering at a restaurant"
    A **PVC** is your **order** ("a 5Gi steak, well done"). The **StorageClass** is the
    **menu item** describing how the kitchen makes it. The **PV** is the **plated dish**
    delivered to your table. You (the app) never enter the kitchen (Ceph) — you just
    order from the menu and receive food.

### 8.2 Why Rook-Ceph on bare metal

TicketHub needs three *kinds* of storage, and Ceph provides all three from one cluster:

![Ceph storage types](assets/diagrams/08-storage-types.png)

| Type | Ceph API | Access mode | TicketHub use |
|------|----------|-------------|---------------|
| **Block** | RBD | `ReadWriteOnce` | Postgres, Kafka, Redis data dirs |
| **File** | CephFS | `ReadWriteMany` | Shared uploads read by many pods |
| **Object** | RGW (S3) | HTTP | Search index snapshots, backups, ticket PDFs |

**Rook** is the Kubernetes **operator** that runs and manages Ceph for you — turning a notoriously complex storage system into declarative CRDs.

![Rook-Ceph architecture](assets/diagrams/08-rook-ceph-arch.png)

| Ceph daemon | Role |
|-------------|------|
| **mon** (x3) | Keep the cluster map + quorum (odd count, like etcd) |
| **mgr** | Metrics, dashboard, orchestration |
| **OSD** (one per disk) | Store the actual data on raw NVMe |

### 8.3 Deploying Rook-Ceph on the data pool

Ceph runs on the **data** node pool (tainted, local NVMe from Chapter 3):

```yaml
# repo/manifests/10-platform/ceph-cluster.yaml (excerpt)
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  mon: { count: 3, allowMultiplePerNode: false }   # quorum, spread across hosts
  storage:
    useAllNodes: false
    nodes:
      - name: worker-data-1
        devices: [{ name: "nvme1n1" }]
      - name: worker-data-2
        devices: [{ name: "nvme1n1" }]
      - name: worker-data-3
        devices: [{ name: "nvme1n1" }]
  placement:
    all:
      tolerations:
        - key: data
          operator: Exists
          effect: NoSchedule
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
            - matchExpressions:
                - { key: pool, operator: In, values: [data] }
```

### 8.4 Defining StorageClasses (the architect's catalog)

```yaml
# repo/manifests/10-platform/storageclass-block.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: rook-ceph-block                 # the "gold" tier for databases
provisioner: rook-ceph.rbd.csi.ceph.com
parameters:
  pool: replicapool
  imageFormat: "2"
  csi.storage.k8s.io/fstype: ext4
reclaimPolicy: Retain                   # keep data if PVC deleted (safety for DBs)
allowVolumeExpansion: true              # grow volumes online
volumeBindingMode: WaitForFirstConsumer # bind only once a pod is scheduled
```

!!! key "Two StorageClass settings every architect must set deliberately"
    - **`reclaimPolicy`**: `Retain` for anything precious (databases) so deleting a
      PVC doesn't wipe data; `Delete` for scratch/ephemeral.
    - **`volumeBindingMode: WaitForFirstConsumer`**: delays PV creation until the pod
      is scheduled, so the volume lands in the **same failure domain/zone** as the pod.
      Critical for topology-aware placement.

!!! note "CSI — the storage plugin standard"
    The `provisioner` value (`rook-ceph.rbd.csi.ceph.com`) is a **CSI (Container Storage
    Interface)** driver. CSI is the vendor-neutral plugin API that lets Kubernetes provision,
    attach, snapshot, and expand volumes on *any* backend — Ceph here, a cloud disk
    elsewhere — without Kubernetes knowing the storage internals. Rook ships the Ceph CSI
    driver; the StorageClass just names it.

### 8.5 A developer consuming storage

A stateful workload just asks — the platform delivers:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
  namespace: data
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: rook-ceph-block
  resources:
    requests:
      storage: 20Gi
```

```bash
kubectl get pvc,pv -n data
# PVC Bound to an auto-created PV, backed by a Ceph RBD image.
```

For StatefulSets (Postgres, Kafka), we don't even write PVCs by hand — `volumeClaimTemplates` mints one **per replica** with stable identity (Chapter 14).

### 8.6 Access modes (know the difference)

| Mode | Meaning | Backed by |
|------|---------|-----------|
| **RWO** ReadWriteOnce | One node mounts read-write | Ceph RBD (block) |
| **RWX** ReadWriteMany | Many nodes mount read-write | CephFS (file) |
| **ROX** ReadOnlyMany | Many nodes mount read-only | CephFS |

!!! warning "Don't ask a database for RWX"
    Databases want **RWO block** storage — a single writer with block semantics. Trying
    to run Postgres on an **RWX** shared filesystem invites corruption. Reserve **RWX**
    (CephFS) for genuinely shared, concurrency-safe use (static assets, uploads).

!!! success "Chapter 8 checklist"
    - **Rook operator + CephCluster** running on the **data** pool (3 mons, OSDs on NVMe).
    - **StorageClasses** defined: block (DBs), file (shared), object (S3/backups).
    - `reclaimPolicy` and `volumeBindingMode` set deliberately per tier.
    - Dynamic provisioning verified: a PVC **Binds** to an auto-created PV.
    - Access modes matched to workloads (RWO for DBs, RWX for shared).

---
