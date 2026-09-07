# TicketHub — Companion Kubernetes Manifests & Services

Runnable companion code for the textbook **"Designing, Installing & Operating a
Production Kubernetes Cluster"** (`../k8s-architecture.pdf`).

Everything here maps to a chapter in the book. Manifests are organized by
**bootstrap order** (Chapter 9) so they can be applied top-to-bottom, or wired
into Argo CD sync waves (Chapter 28).

## Layout

```
repo/
├── services/            # one folder per microservice (Dockerfiles + app stubs)  [Part III]
│   ├── frontend/
│   ├── gateway/
│   ├── users/
│   ├── catalog/
│   ├── inventory/
│   ├── orders/
│   ├── payments/
│   ├── notifications/
│   └── search/
└── manifests/
    ├── 00-namespaces/   # namespaces, ResourceQuota, LimitRange              [Ch 9]
    ├── 10-platform/     # MetalLB, Cilium Gateway API, Rook-Ceph, StorageClasses  [Ch 6-8]
    ├── 20-data/         # Postgres, Redis, Kafka StatefulSets                [Ch 11,14]
    ├── 30-workloads/    # Deployments + Services for the 9 services          [Ch 11-12]
    ├── 40-config/       # ConfigMaps + Secrets                               [Ch 13]
    ├── 50-scaling/      # HPA / VPA / KEDA / PriorityClass / PDB             [Ch 16-17]
    ├── 60-security/     # RBAC, NetworkPolicy, Kyverno, Falco                [Ch 19-23]
    └── 70-observability/# Prometheus, Grafana, Loki                          [Ch 26]
```

The `argocd/` folder holds the app-of-apps that delivers all of the above via
GitOps sync waves (Chapter 28).

## Per-manifest documentation

Every `*.yaml` under `manifests/` has a sibling `*.md` that explains what the
manifest is, the objects it defines, and — with a color-coded relationship
diagram — how it interacts with the other pods, services, secrets, and policies
in the cluster. Each doc also links to the relevant textbook chapter. Open the
`.md` next to any manifest (for example
[`20-data/postgres-statefulset.md`](manifests/20-data/postgres-statefulset.md))
to start.

## Apply order (manual)

```bash
kubectl apply -f manifests/00-namespaces/
# platform (Helm charts in the book; raw CRs here)
kubectl apply -f manifests/10-platform/
kubectl apply -f manifests/20-data/
kubectl apply -f manifests/30-workloads/
kubectl apply -f manifests/40-config/
kubectl apply -f manifests/50-scaling/
kubectl apply -f manifests/60-security/
kubectl apply -f manifests/70-observability/
```

> In production these are delivered by Argo CD (`repo/argocd/`), not applied by
> hand — Git is the source of truth. The manual order above mirrors the
> Chapter 9 bootstrap sequence for local testing. The root app-of-apps points at
> `repo/argocd/apps/`, where each manifest layer is its own child Application with
> a sync wave (Chapter 28).

## Continuous delivery

CI (`.github/workflows/ci.yml`) builds, tests, and **signs** an image per changed
service, then a `promote` job pins the **signed digest** into the matching
`manifests/30-workloads/<svc>-deployment.yaml` and opens a pull request. Merging
the PR is the deploy approval; Argo CD then rolls out the new digest. CI never
holds cluster credentials (Chapter 28).

## Status

| Part | Content | State |
|------|---------|-------|
| II | Namespaces, quotas, MetalLB, StorageClasses, Ceph, Gateway API | ✅ included |
| III | Dockerfiles + workloads for all 9 services (Deployments, StatefulSets, Services, config) | ✅ included |
| IV | Autoscaling (HPA/VPA/KEDA), PDB, PriorityClasses | ✅ included |
| V | RBAC, NetworkPolicy (per-service zero-trust), Kyverno, Falco | ✅ included |
| VI | Prometheus/alerts, Velero backup, Argo CD app-of-apps + CI promotion | ✅ included |
