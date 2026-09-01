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


### 28.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Argo CD `sync` applies manifests in dependency order via sync waves**, but the wave mechanism is opt-in (annotation `argocd.argoproj.io/sync-wave: "N"`). Without explicit wave annotations, Argo CD applies all resources simultaneously — which can create ordering failures (e.g., a Deployment being created before its ConfigMap or Secret exists).
    - **Argo CD App of Apps does not automatically prune child Applications when removed from the parent**: if you remove a child Application from the App of Apps, Argo CD marks it `OutOfSync` but doesn't delete it unless `prune: true` is set. Dangling Applications keep running and consuming resources indefinitely.
    - **`kubectl apply` vs Argo CD sync**: Argo CD uses server-side apply with a `argocd` field manager. If you also run `kubectl apply` manually on the same resource, field manager conflicts can cause Argo CD to revert your changes or generate `FieldValueConflict` errors. All changes to Argo CD-managed resources MUST go through git.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Argo CD sync with `--force` flag deletes and recreates resources**: unlike `kubectl apply --force`, this is destructive — Argo CD will DELETE a running StatefulSet and recreate it, causing a full restart. Only use force sync when absolutely necessary (stuck CRD migration), never as a routine operation.
    - **Repo server access to private registries**: Argo CD's repo server must have git credentials to pull from private repos AND registry credentials if using Helm OCI charts from a private registry. Missing credentials cause silent sync failures with opaque "repository not found" errors.
    - **Automated sync + Kyverno mutating webhooks**: Argo CD's drift detection compares the DESIRED manifest (git) against the LIVE manifest (cluster). Kyverno's mutation adds fields to the live manifest that aren't in git — causing Argo CD to always show the app as `OutOfSync`. Configure Argo CD's `ignoreDifferences` for Kyverno-injected fields to prevent false-positive sync loops.

!!! question "Architect Considerations"
    1. **Mono-repo vs multi-repo**: a single `repo/manifests/` tree (as in this project) is easy to navigate but creates a single failure domain for gitops — a broken PR that blocks merge prevents ALL service updates. A multi-repo layout (one repo per service team) gives team autonomy but multiplies Argo CD Application count and makes cross-service dependencies harder to express.
    2. **Secrets in git with Argo CD**: application secrets cannot be stored in plaintext in git. Options: Sealed Secrets (encrypted in git, decrypted in cluster), External Secrets (fetched from Vault at sync time), Argo CD Vault Plugin (template substitution at sync time). External Secrets is the cleanest architecture — git contains only the ExternalSecret declaration, Vault holds the actual value.
    3. **Sync windows for compliance**: some environments require that no changes are applied between Friday 5pm and Monday 9am (change freeze). Argo CD `SyncWindow` supports this — define `denyWindows` for change freeze periods. Without this, an auto-synced Argo CD will apply a Friday 11pm merge immediately.
    4. **Rollback strategy**: Argo CD "rollback" is `git revert` + sync. There is no in-cluster rollback button that is independent of git state. Ensure your team understands this: to roll back a bad deploy, you must create a git commit that reverts the change and merge it to main. Design your branch protection and merge strategy around this constraint.
    5. **ApplicationSet for multi-environment**: use Argo CD ApplicationSet with a directory generator to automatically create Applications for every environment directory (`envs/staging/`, `envs/prod/`). This avoids manually copying Application objects between environments and ensures all environments have the same Application structure.

!!! success "Chapter 28 checklist"
    - **Git is the single source of truth**; changes flow through reviewed PRs.
    - **Argo CD** syncs with `selfHeal` + `prune`; manual drift is reverted.
    - **app-of-apps + sync waves** encode the Chapter 9 bootstrap order — full cluster reproducible from Git.
    - CI **builds/signs images and opens PRs only** — never holds cluster credentials.
    - Risky releases use **Argo Rollouts** canary with metric-based auto-rollback.
    - Secrets via **External/Sealed Secrets**, never plaintext in Git.

---
