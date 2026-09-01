## <a name="ch25"></a>25. Extending Kubernetes — CRDs & Operators

Almost every platform component in this book — Cilium, Rook-Ceph, MetalLB, cert-manager, Kyverno, Prometheus — is installed by defining **custom resources** that Kubernetes doesn't ship with. That's not a coincidence: it's the **operator pattern**, the way Kubernetes is meant to be extended. This chapter closes Part V by explaining the machinery you've been using all along.

### 25.1 CustomResourceDefinitions — teaching the API new nouns

A **CRD** registers a new resource *kind* with the API server. After applying a CRD, `kubectl get postgresclusters` works as if it were built in — same RBAC, same `kubectl`, same declarative YAML.

![CRD and operator](assets/diagrams/25-crd-operator.png)

| Native | Custom (via CRD) |
|--------|------------------|
| `kind: Deployment` | `kind: CephCluster` |
| `kind: Service` | `kind: CiliumNetworkPolicy` |
| `kind: Secret` | `kind: ClusterPolicy` (Kyverno) |

```yaml
# a CRD (abbreviated) — this is what an operator ships
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: { name: postgresclusters.tickethub.io }
spec:
  group: tickethub.io
  names: { kind: PostgresCluster, plural: postgresclusters }
  scope: Namespaced
  versions:
    - name: v1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                replicas: { type: integer }
                version:  { type: string }
```

### 25.2 The operator — a controller with domain knowledge

A CRD by itself is inert — just a new noun in the database. The **operator** is the **controller** that gives it behavior: it watches those custom resources and drives the real world to match, using the same **reconcile loop** Kubernetes uses internally.

![Operator pattern](assets/diagrams/25-operator-pattern.png)

```text
loop forever:
    observe  = read desired state (the CR) + actual state (real objects)
    diff     = compute the difference
    act      = create / update / delete to converge
```

!!! mental "Mental model — hiring an expert DBA who never sleeps"
    Running Postgres HA by hand needs a **DBA**: provision disks, configure replication,
    fail over the primary, take backups. An **operator encodes that DBA's knowledge as
    software**. You declare `kind: PostgresCluster, replicas: 3`; the operator does
    everything a human DBA would — continuously, at 3am, without a ticket. The CRD is the
    *request form*; the operator is the *tireless expert* fulfilling it.

### 25.3 Why this matters for TicketHub

You've relied on operators throughout the build:

| Custom resource | Operator | What it automates |
|-----------------|----------|-------------------|
| `CephCluster` | Rook | Provisions/heals Ceph (Ch 8) |
| `CiliumNetworkPolicy` | Cilium | eBPF network enforcement (Ch 6, 21) |
| `IPAddressPool` | MetalLB | Bare-metal LoadBalancer IPs (Ch 7) |
| `Certificate` | cert-manager | Issues/renews TLS (Ch 7) |
| `ClusterPolicy` | Kyverno | Admission policy (Ch 22) |
| `ScaledObject` | KEDA | Event-driven scaling (Ch 16) |

!!! key "Prefer a mature operator over hand-rolled YAML for stateful systems"
    You *could* run Postgres with a raw StatefulSet (Chapter 14) — but failover, backups,
    and version upgrades are then your problem. A battle-tested operator (CloudNativePG,
    Strimzi for Kafka) encodes years of operational hard-won lessons. For complex stateful
    software, adopt the operator; reserve hand-written manifests for your own stateless apps.

### 25.4 When to write your own

Most teams **consume** operators; occasionally you **build** one — to encode *your* domain, e.g. a `TicketHubTenant` CRD that provisions a namespace, quota, network policies, and per-tenant databases in one declarative object. Frameworks like **Kubebuilder** and the **Operator SDK** scaffold the controller so you write only the reconcile logic.

!!! warning "An operator is a privileged controller — scope it tightly"
    Operators typically hold broad RBAC (they create Deployments, Secrets, PVCs). A
    compromised or buggy operator is high-blast-radius. Install operators from trusted
    sources, pin versions, review their RBAC, and give each the **narrowest** ClusterRole
    that lets it do its job (Chapter 19).

### 25.5 DB Replication as a CRD domain — a worked example {#255-db-replication-as-a-crd-domain}

This section walks through the two CRDs that model Postgres HA replication for
TicketHub (`repo/manifests/20-data/postgres-replication-crd.yaml`) as a
concrete, fully annotated example of the operator pattern in practice.

#### 25.5.1 The domain model

Running Postgres with streaming replication involves multiple moving parts:

| Concern | Without CRDs | With CRDs + operator |
|---|---|---|
| Primary/standby topology | Init-containers + shell scripts | Declared as `spec.instances` + `replication.*` |
| Failover | Custom watchdog sidecar | `failover.automaticFailover: true` |
| Connection pooling | Hand-written PgBouncer manifests | `connectionPooler.enabled: true` |
| WAL archiving (PITR) | Custom cron + pgbackrest scripts | `walArchive.destination: s3://...` |
| Replication slot lifecycle | DBA monitors `pg_replication_slots` | `kind: ReplicationSlot` with `retentionPolicy` |
| Observability | Manually deploy postgres_exporter | `monitoring.enablePodMonitor: true` |

The CRD approach doesn't hide complexity — it **relocates** it from your
per-cluster scripts into a shared, versioned, tested operator.

#### 25.5.2 CRD structure and operator reconcile flow

![DB replication CRD flow](assets/diagrams/25-db-replication-crd.png)

Two CRDs compose the domain:

**`PostgresReplicationCluster`** — the top-level resource declaring the desired
cluster state. Key `spec` fields:

```yaml
spec:
  instances: 3                       # 1 primary + 2 standbys
  replication:
    synchronousMode: quorum          # RPO = 0 for 1-standby loss
    walLevel: replica                # replica | logical
    hotStandby: true                 # read-only Service for standbys
  walArchive:
    enabled: true
    destination: s3://tickethub-wal/postgres
  failover:
    automaticFailover: true
    promotionTimeout: 60
  connectionPooler:
    enabled: true
    poolMode: transaction
  storage:
    size: 20Gi
    storageClass: rook-ceph-block
```

**`ReplicationSlot`** — a dependent resource for named logical or physical
replication slots. Logical slots (for CDC pipelines like Debezium) require
`walLevel: logical` on the parent cluster:

```yaml
apiVersion: db.tickethub.io/v1alpha1
kind: ReplicationSlot
metadata:
  name: tickethub-cdc-slot
  namespace: data
spec:
  clusterRef: tickethub-postgres
  type: logical
  plugin: pgoutput
  retentionPolicy:
    maxWalSize: 2Gi
    inactiveTimeout: 24h
```

The `retentionPolicy` is critical: an abandoned logical slot with no consumer
accumulates WAL indefinitely. The operator watches `pg_replication_slots` and
drops slots that breach `maxWalSize` or `inactiveTimeout`, firing a Kubernetes
`Warning` event so the platform team is notified.

#### 25.5.3 What the operator reconciles

Each time the `tickethub-db-operator` sees a `PostgresReplicationCluster`
event (create, update, status-drift) it drives the following objects:

| Object created/owned | Purpose |
|---|---|
| `StatefulSet postgres` | Runs N Postgres instances with per-pod PVCs |
| `Service postgres-rw` | ClusterIP → primary pod (`role=primary`) |
| `Service postgres-ro` | ClusterIP → all standby pods (`role=standby`) |
| `Deployment pgbouncer` | PgBouncer connection pool (if `connectionPooler.enabled`) |
| `PodMonitor postgres` | Prometheus scrape config for `postgres_exporter` sidecar |
| `Secret pgbouncer-config` | PgBouncer `pgbouncer.ini` generated from CR spec |
| Physical `ReplicationSlot` CRs | Auto-created per standby by the operator |

#### 25.5.4 The operator RBAC

Because the operator manages StatefulSets, Services, Secrets, and its own CRDs,
its ClusterRole is broad — but scoped as tightly as possible:

```yaml
# repo/manifests/20-data/postgres-replication-crd.yaml (ClusterRole excerpt)
rules:
  - apiGroups: [db.tickethub.io]
    resources: [postgresreplicationclusters, replicationslots,
                postgresreplicationclusters/status, replicationslots/status]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [apps]
    resources: [statefulsets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [""]
    resources: [pods, pods/exec, services, endpoints,
                persistentvolumeclaims, configmaps, secrets]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: [monitoring.coreos.com]
    resources: [podmonitors]
    verbs: [get, list, watch, create, update, patch, delete]
```

`pods/exec` is needed for `pg_promote()` and `pg_rewind` — the operator shells
into the standby to run the promotion. This is **high-privilege**; the operator
ServiceAccount is restricted to the `data` namespace via RoleBinding if the
`pods/exec` scope were namespace-only, but because StatefulSet management is
cluster-scoped here a ClusterRoleBinding is used. In production, prefer a
per-namespace operator deployment to limit the blast radius.

#### 25.5.5 Observing the running cluster

```bash
# Short-form thanks to shortNames in the CRD
kubectl -n data get pgrc
# NAME                 PRIMARY          INSTANCES  READY  PHASE    AGE
# tickethub-postgres   postgres-0       3          3      Healthy  4d

# Replication lag per standby
kubectl -n data get pgrc tickethub-postgres -o jsonpath='{.status.replicationLag}'
# {"postgres-1":"0/0 (0 bytes)","postgres-2":"128/0 (128 bytes)"}

# Inspect the logical CDC slot
kubectl -n data get rslot
# NAME                 CLUSTER              TYPE     ACTIVE  WALLAG
# tickethub-cdc-slot   tickethub-postgres   logical  true    512 bytes
```

#### 25.5.6 Failover sequence

When the primary disappears the operator fires the following reconcile actions
(visible in `kubectl describe pgrc tickethub-postgres`):

1. **Detect** — health-check goroutine misses `promotionTimeout` heartbeats.
2. **Elect** — rank standbys by `pg_last_wal_receive_lsn`; least lag wins.
3. **Promote** — `exec postgres-1 -- pg_ctl promote`.
4. **Re-label** — `kubectl label pod postgres-1 role=primary`; Service
   endpoint shifts in < 1 s.
5. **Rewind** — when `postgres-0` recovers, run `pg_rewind` to re-sync it as a
   new standby.
6. **Status** — update `status.currentPrimary: postgres-1`, emit Event.

The entire sequence is typically complete within 30–90 seconds — far faster and
more reliable than a human paged at 3 AM.

!!! success "Chapter 25 checklist — Part V complete"
    - Understand CRDs (**new API nouns**) + operators (**controllers that reconcile them**).
    - Stateful systems (DB, Kafka, Ceph) run via **mature operators**, not hand-rolled YAML.
    - Operator RBAC reviewed and **scoped tightly**; versions pinned; sources trusted.
    - Custom operators (if any) scaffolded with Kubebuilder/Operator SDK.
    - **DB replication** is modelled as two CRDs: `PostgresReplicationCluster` (topology,
      failover, pooling, WAL archive) and `ReplicationSlot` (slot lifecycle + retention).
    - `synchronousMode: quorum` + `automaticFailover: true` achieves RPO = 0 with
      automated promotion — no DBA required at 3 AM.

    TicketHub is now **secured end to end**: identity (RBAC), the pod (PSA/SecurityContext),
    the network (NetworkPolicy), policy (Kyverno), runtime (Falco), and the supply chain
    (encryption + signing). **Part VI** operates it: observability, backup/DR, upgrades,
    and GitOps delivery.

---
