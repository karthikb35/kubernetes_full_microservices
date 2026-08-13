## <a name="ch28"></a>28. GitOps Delivery with Argo CD

Throughout this book we've written YAML and imagined `kubectl apply`. In production, **nobody applies manifests from a laptop**. Instead, **Git is the single source of truth**, and **Argo CD** continuously reconciles the cluster to match it. This is **GitOps** — it makes deployments auditable, reproducible, self-healing, and trivially reversible.

### 28.1 The GitOps model

![GitOps flow](assets/diagrams/28-gitops-flow.png)

1. Desired state (all the manifests from this book) lives in **Git**.
2. A change is a **pull request** — reviewed, approved, merged.
3. **Argo CD** detects the commit and **applies** it to the cluster.
4. If anything **drifts** from Git (a manual `kubectl edit`), Argo CD **detects and reverts** it.

!!! mental "Mental model — Git as the thermostat setting"
    You don't walk around the house adjusting each radiator (`kubectl apply` per resource).
    You set the **thermostat** (Git), and the system continuously works to match it. Open a
    window and the temperature drifts — the thermostat notices and compensates (Argo CD
    self-heals). Want it warmer? Change the *setting* (a commit), not the radiators. The
    desired state is declared in one reviewed place; the system enforces it.

### 28.2 Push vs. pull delivery

| | Traditional (push) | GitOps (pull) |
|--|--------------------|---------------|
| Trigger | CI runs `kubectl apply` | Argo CD pulls Git |
| Credentials | CI holds cluster admin | Cluster pulls; CI never touches it |
| Drift | Undetected | Detected + reverted |
| Audit | Scattered CI logs | Git history = full audit trail |
| Rollback | Re-run old pipeline | `git revert` |

!!! key "GitOps means the cluster pulls — CI never holds cluster credentials"
    In push delivery, your CI system holds cluster-admin and becomes a juicy target. In
    GitOps, **Argo CD (inside the cluster) pulls from Git** — CI only builds images and
    opens PRs, and never has kubectl access. This shrinks the attack surface and makes every
    change traceable to a signed commit.

### 28.3 The Application and app-of-apps

An Argo CD **Application** maps a Git path to a cluster destination:

```yaml
# repo/argocd/tickethub-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tickethub
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal/tickethub/platform.git
    targetRevision: main
    path: repo/manifests/30-workloads
  destination:
    server: https://kubernetes.default.svc
    namespace: tickethub
  syncPolicy:
    automated:
      prune: true                 # delete resources removed from Git
      selfHeal: true              # revert manual drift
    syncOptions: [CreateNamespace=true]
```

The **app-of-apps** pattern uses one **root** Application to manage all the others — and encodes the **bootstrap order from Chapter 9** as **sync waves**:

![Sync waves](assets/diagrams/28-sync-waves.png)

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "3"    # Rook-Ceph in wave 3, apps in wave 9
```

This is the payoff of Chapter 9's ordering discipline: the **entire platform reconstructs itself from Git, in the correct order**, on a fresh cluster — the ultimate DR complement to Chapter 27.

### 28.4 Progressive delivery

Argo CD deploys the declared state; **Argo Rollouts** adds **canary** and **blue-green** strategies (Chapter 18) on top — shift 10% of traffic to the new version, watch the Prometheus error rate (Chapter 26), and **auto-rollback** if the SLO degrades.

```yaml
strategy:
  canary:
    steps:
      - setWeight: 10
      - pause: { duration: 5m }        # bake, watch metrics
      - setWeight: 50
      - pause: { duration: 5m }
      - setWeight: 100
```

!!! warning "Secrets still don't go in Git — even with GitOps"
    GitOps wants *everything* in Git, but plaintext secrets must **not** be. Use the
    **External Secrets** pattern from Chapter 13 (Git holds the `ExternalSecret` reference;
    the vault holds the value) or Sealed Secrets. Argo CD syncs the reference; the real
    credential never lands in a commit.

!!! success "Chapter 28 checklist"
    - **Git is the single source of truth**; changes flow through reviewed PRs.
    - **Argo CD** syncs with `selfHeal` + `prune`; manual drift is reverted.
    - **app-of-apps + sync waves** encode the Chapter 9 bootstrap order — full cluster reproducible from Git.
    - CI **builds/signs images and opens PRs only** — never holds cluster credentials.
    - Risky releases use **Argo Rollouts** canary with metric-based auto-rollback.
    - Secrets via **External/Sealed Secrets**, never plaintext in Git.

---
