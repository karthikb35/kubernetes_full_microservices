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
    ├── 10-platform/     # MetalLB, NGINX Ingress, Rook-Ceph, StorageClasses  [Ch 6-8]
    ├── 20-data/         # Postgres, Redis, Kafka StatefulSets                [Ch 11,14]
    ├── 30-workloads/    # Deployments + Services for the 9 services          [Ch 11-12]
    ├── 40-config/       # ConfigMaps + Secrets                               [Ch 13]
    ├── 50-scaling/      # HPA / VPA / KEDA / PriorityClass / PDB             [Ch 16-17]
    ├── 60-security/     # RBAC, NetworkPolicy, Kyverno, Falco                [Ch 19-23]
    └── 70-observability/# Prometheus, Grafana, Loki                          [Ch 26]
```

The `argocd/` folder holds the app-of-apps that delivers all of the above via
GitOps sync waves (Chapter 28).

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
> Chapter 9 bootstrap sequence for local testing.

## Status

| Part | Content | State |
|------|---------|-------|
| II | Namespaces, quotas, MetalLB, StorageClasses, Ceph, Ingress | ✅ included |
| III | Service Dockerfiles + workloads (Deployments, StatefulSets, Services, config) | ✅ included |
| IV | Autoscaling (HPA/VPA/KEDA), PDB, PriorityClasses | ✅ included |
| V | RBAC, NetworkPolicy, Kyverno, Falco | ✅ included |
| VI | Prometheus/alerts, Velero backup, Argo CD app-of-apps | ✅ included |
