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

!!! success "Chapter 27 checklist"
    - **etcd snapshots** + **Velero** backups scheduled; PV data snapshotted.
    - **RPO/RTO** defined and validated by periodic **restore drills**.
    - Node maintenance always via **cordon → drain → uncordon**, honoring PDBs.
    - Upgrades: **back up first**, control plane before workers, one node at a time, no skipped minors.
    - DR playbook documented and rehearsed on a scratch cluster.

---
