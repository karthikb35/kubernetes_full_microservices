## <a name="ch27"></a>27. Backup, DR, Upgrades & Node Maintenance

A production cluster is never "done" — nodes need patching, Kubernetes needs upgrading, and someday something *will* fail catastrophically. This chapter covers keeping TicketHub alive through planned maintenance and unplanned disaster: **backup**, **disaster recovery**, **cluster upgrades**, and **node maintenance** — all without dropping a single ticket sale where avoidable.

### 27.1 What actually needs backing up

| Layer | Contains | Backup method |
|-------|----------|---------------|
| **etcd** | All cluster state (every object) | `etcdctl snapshot` (scheduled) |
| **PV data** | Database contents, Kafka logs | CSI volume snapshots (Ceph) |
| **API objects** | Deployments, ConfigMaps, RBAC | Velero |
| **Git repo** | Desired state (Chapter 28) | Git is already the backup |

Because TicketHub is **GitOps-delivered** (next chapter), the *manifests* are safe in Git. What Git *doesn't* hold is **stateful data** and **secrets** — that's what backup tooling protects.

### 27.2 Velero — application-level backup & DR

**Velero** backs up both the **Kubernetes API objects** and the **persistent volume data** (via CSI snapshots) to object storage (Ceph RGW / S3), and restores them to the same or a **brand-new cluster** — the foundation of disaster recovery.

![Velero](assets/diagrams/27-velero.png)

```yaml
# repo/manifests/70-observability/velero-schedule.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-tickethub
  namespace: velero
spec:
  schedule: "0 2 * * *"            # 02:00 daily
  template:
    includedNamespaces: [tickethub, data]
    snapshotVolumes: true          # CSI snapshot the PVs too
    ttl: 720h0m0s                  # keep 30 days
```

```bash
velero backup create adhoc-before-upgrade --include-namespaces tickethub,data
velero restore create --from-backup daily-tickethub-20260811020000   # DR
```

!!! mental "Mental model — backups are a time machine, DR is a spare house"
    A **backup** is a **time machine**: go back to yesterday's state if today breaks. **DR**
    is having a **fully furnished spare house** in another town: if your house burns down,
    you move in and keep living. Velero is both — snapshots to rewind, and cross-cluster
    restore to relocate. An untested backup is a spare house you've never checked has a roof.

!!! key "A backup you haven't restored is a hope, not a plan"
    Schedule a **periodic restore drill** into a scratch cluster/namespace. Teams discover
    at the worst possible moment that snapshots were app-inconsistent, a PV class didn't
    exist on the target, or a secret was missing. Define **RPO** (how much data you can lose)
    and **RTO** (how fast you must be back), and prove you meet them.

### 27.3 Node maintenance — cordon & drain

To patch or reboot a node, evict its pods **gracefully** first. `cordon` stops new pods landing; `drain` evicts existing ones while **respecting PodDisruptionBudgets** (Chapter 17).

![Node drain](assets/diagrams/27-node-drain.png)

```bash
kubectl cordon node-3                       # unschedulable
kubectl drain node-3 --ignore-daemonsets --delete-emptydir-data   # evict, honors PDBs
# ... patch OS / reboot ...
kubectl uncordon node-3                      # back into rotation
```

!!! warning "Drain without PDBs can take a service to zero"
    `drain` evicts *all* a node's pods at once. If a PDB doesn't guarantee `minAvailable`,
    and replicas happened to co-locate, the service briefly hits zero. This is exactly why
    Chapter 17 mandated a PDB on every user-facing service — maintenance safety depends on it.

### 27.4 Upgrading Kubernetes

Upgrade in a strict order, honoring the **version-skew** rules, with an etcd backup first:

![Upgrade order](assets/diagrams/27-upgrade-order.png)

```bash
# 0. back up first
etcdctl snapshot save /backup/etcd-$(date +%F).db
velero backup create pre-upgrade --include-namespaces tickethub,data

# 1. control plane, one node at a time
kubeadm upgrade plan
kubeadm upgrade apply v1.31.0        # on cp-1, then cp-2, cp-3

# 3. workers, rolling: cordon -> drain -> upgrade kubelet -> uncordon
```

| Rule | Detail |
|------|--------|
| **Order** | Control plane **before** workers |
| **Skew** | kubelet may be **one minor version** behind the API server, never ahead |
| **One at a time** | Preserve HA quorum (etcd, Chapter 3) throughout |
| **Never skip minors** | 1.30 → 1.31 → 1.32, not 1.30 → 1.32 |


### 27.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Velero backs up Kubernetes resource definitions (etcd objects), NOT application data volumes** by default. The `--include-volumes` flag or CSI volume snapshot integration is required to back up PVC data. A Velero backup without volume snapshots can restore a StatefulSet definition but not the database data it contained.
    - **etcd backup is a different layer from Velero backup**: etcd snapshot (`etcdctl snapshot save`) backs up the raw cluster state including Secrets, RBAC, and CRDs. Velero backup backs up namespaced resources but cannot restore cluster-scoped objects (Nodes, ClusterRoles, StorageClasses) without specific `--include-cluster-resources` flags. Both are required for full DR.
    - **Kubernetes version skew policy**: you can upgrade only one minor version at a time (`1.29 → 1.30`, not `1.29 → 1.31`). Control plane components can be ahead of kubelets by up to 2 minor versions during rolling upgrades, but kubelets cannot be ahead of the API server. The upgrade order is always: etcd → kube-apiserver → other CP components → kubelets.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`velero backup create` vs `velero schedule create`**: one-time backups expire and are deleted based on the TTL. Without a schedule, a manual backup from 6 months ago is your most recent backup when you need it most. Always configure a scheduled backup from day 1.
    - **PVC snapshot CSI driver compatibility**: Velero CSI volume snapshots require the storage driver to support the `VolumeSnapshot` API. Rook-Ceph's CSI driver supports it, but you must install the `snapshot.storage.k8s.io` CRD and the external-snapshotter controller separately. Not having these installed means Velero silently skips volume backups.
    - **In-place node upgrade vs blue-green**: `kubeadm upgrade node` upgrades the kubelet in place. If the upgrade fails mid-way, the node may be in a partially upgraded state that prevents normal operation. Always have a node replacement strategy (provision new node, drain old, decommission) as a fallback — especially for production clusters where rebuild time is critical.

!!! question "Architect Considerations"
    1. **RTO and RPO definition**: define these BEFORE building the backup system. For TicketHub: is a 4-hour RTO acceptable (rebuild cluster + restore backup)? Is a 1-hour RPO acceptable (lose up to 1 hour of orders)? These requirements drive the backup frequency, snapshot consistency level, and restore automation investment.
    2. **Backup verification — "trust but verify"**: a backup that has never been tested is a hypothesis, not a guarantee. Schedule quarterly DR drills: restore the entire `data` namespace to a separate cluster and run smoke tests. Track the actual restore time — it's almost always longer than estimated.
    3. **Cluster upgrade strategy for bare metal**: you cannot "spin up a new node" on demand like in cloud. For bare metal, the upgrade strategy is: drain workers one by one, upgrade kubelet, uncordon. For control plane: use the HA topology (3 CP nodes) so you upgrade one at a time with 2/3 quorum intact.
    4. **etcd compaction and defragmentation**: etcd accumulates historical revision data that is only freed by compaction (`etcdctl compact`) and defragmentation (`etcdctl defrag`). A production cluster that has been running for months without defragmentation can have etcd databases 10× larger than necessary, increasing backup size and restore time.
    5. **Multi-cluster DR topology**: a single on-prem cluster with backup to the same data center Ceph storage is not a true DR — a data center fire destroys both the cluster and the backup. For genuine DR, Velero backups must be replicated to an off-site location (different data center, cloud storage bucket).

!!! success "Chapter 27 checklist"
    - **etcd snapshots** + **Velero** backups scheduled; PV data snapshotted.
    - **RPO/RTO** defined and validated by periodic **restore drills**.
    - Node maintenance always via **cordon → drain → uncordon**, honoring PDBs.
    - Upgrades: **back up first**, control plane before workers, one node at a time, no skipped minors.
    - DR playbook documented and rehearsed on a scratch cluster.

---
