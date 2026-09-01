## <a name="ch22"></a>22. Policy as Code — Kyverno (Validate, Mutate, Generate)

PSA and RBAC are powerful but coarse. Real organizations have dozens of finer rules: *no `:latest` tags, every pod must have resource limits, images only from our registry, every namespace gets a default-deny NetworkPolicy*. Encoding these by hand is unenforceable. **Kyverno** makes them **policy as code** — plain YAML policies enforced at admission, cluster-wide, automatically.

### 22.1 Kyverno sits in the admission path

![Kyverno admission](assets/diagrams/22-kyverno-admission.png)

Kyverno is an **admission webhook**. Every create/update passes through it before persistence, where it can **validate** (allow/deny), **mutate** (modify), or **generate** (create companion resources).

!!! mental "Mental model — an automated plan-checker at city hall"
    Before any building permit (manifest) is approved, it goes to an **automated
    plan-checker**. It **rejects** plans that violate code (validate), **auto-corrects**
    small omissions like adding a required label (mutate), and **files companion
    paperwork** for you such as the fire-safety plan (generate). Nothing gets built without
    passing — consistently, without a human in the loop.

### 22.2 The three policy actions

![Policy actions](assets/diagrams/22-policy-actions.png)

| Action | Does | TicketHub example |
|--------|------|-------------------|
| **validate** | Allow/deny based on rules | Reject `:latest`; require resource limits |
| **mutate** | Modify the resource | Inject `seccompProfile`, default labels |
| **generate** | Create linked resources | Auto-create default-deny NetworkPolicy per new namespace |

### 22.3 Validate — block bad specs

```yaml
# repo/manifests/60-security/kyverno-policies.yaml (disallow-latest section)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: Enforce      # Audit first, then Enforce
  rules:
    - name: require-image-tag
      match:
        any: [{ resources: { kinds: [Pod] } }]
      validate:
        message: "Images must use an immutable tag or digest, not latest."
        pattern:
          spec:
            containers:
              - image: "!*:latest"
```

### 22.4 Mutate — inject secure defaults

```yaml
# repo/manifests/60-security/kyverno-policies.yaml (default-securitycontext section)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: add-default-securitycontext }
spec:
  rules:
    - name: default-seccomp
      match:
        any: [{ resources: { kinds: [Pod], namespaces: [tickethub] } }]
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              seccompProfile: { type: RuntimeDefault }
```

### 22.5 Generate — provision companion resources

```yaml
# See: repo/manifests/ for the full manifest
# every new namespace automatically gets a default-deny NetworkPolicy
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: add-default-deny }
spec:
  rules:
    - name: default-deny-netpol
      match:
        any: [{ resources: { kinds: [Namespace] } }]
      generate:
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny-all
        namespace: "{{request.object.metadata.name}}"
        data:
          spec:
            podSelector: {}
            policyTypes: [Ingress, Egress]
```

!!! tip "Always start in Audit, then switch to Enforce"
    Set `validationFailureAction: Audit` first. Kyverno reports every violation in
    **PolicyReports** without blocking anything, so you see the blast radius across
    existing workloads. Fix them, then flip to `Enforce`. Rolling out `Enforce` blind can
    reject legitimate deploys and page you at 2am.

!!! key "Kyverno vs. OPA/Gatekeeper"
    Both are admission-policy engines. **Kyverno** uses plain **YAML** (no new language)
    and uniquely supports **generate** and image verification natively — a gentle on-ramp
    for Kubernetes teams. **OPA/Gatekeeper** uses the **Rego** language, more powerful for
    complex logic but a steeper learning curve. TicketHub standardizes on Kyverno for its
    YAML ergonomics.


### 22.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Kyverno mutation policies run BEFORE validation policies** in the admission chain. This means a mutate policy that injects a default `securityContext` runs first, then a validate policy can check that `securityContext` is present — allowing you to enforce invariants while also providing defaults for teams that haven't set them.
    - **`background: true` (default)** means Kyverno evaluates policies against existing resources periodically, not just at admission time. A new validate policy with `validationFailureAction: enforce` will log violations on pre-existing resources but will NOT delete or modify them — only new or updated objects are blocked.
    - **ClusterPolicy vs Policy scope**: `ClusterPolicy` is cluster-wide; `Policy` is namespace-scoped. Use `ClusterPolicy` for platform-wide invariants (no `latest` tag, no root containers) and namespace-scoped `Policy` for team-specific rules (allowed image registries for namespace X).

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`validationFailureAction: enforce` on a policy that breaks a system component**: if you apply a `ClusterPolicy` that blocks pods without a required label and the Cilium DaemonSet pods don't have that label, Cilium pods cannot be recreated after a crash — taking down all node networking. Always test policies in `audit` mode first and explicitly exclude system namespaces with `exclude.resources.namespaces`.
    - **Kyverno webhook timeout**: Kyverno injects an admission webhook with a default timeout of 10 seconds. If the Kyverno pod is unavailable or slow, ALL pod admissions time out — blocking ALL deployments cluster-wide. Set `failurePolicy: Ignore` on non-critical policies and ensure Kyverno runs with PDB `minAvailable: 1` or is in HA mode.
    - **Generate policies and ownership**: when Kyverno generates a NetworkPolicy in a new namespace, it becomes the owner. Manually editing that NetworkPolicy will cause Kyverno to re-sync it back to the generated version. Either don't generate resources you intend to customize, or use `synchronize: false` to generate-once-and-abandon.

!!! question "Architect Considerations"
    1. **Policy as code in git**: Kyverno ClusterPolicies should live in the `repo/manifests/60-security/` directory and be deployed via Argo CD (Chapter 28). This makes policy changes auditable (git history), reviewable (PR process), and automatically enforced across environments.
    2. **Kyverno vs OPA/Gatekeeper**: Kyverno uses native Kubernetes YAML for policies (lower learning curve); OPA Gatekeeper uses Rego (more expressive for complex rules). For a platform team that primarily maintains Kubernetes manifests, Kyverno's YAML-native approach reduces the cognitive overhead. For complex multi-system policy (spanning cloud APIs, CI/CD, and Kubernetes), OPA is more consistent.
    3. **Exception management**: Kyverno supports `PolicyException` objects (v1.9+) that grant named workloads exemptions from specific policies. This is better than disabling the policy for everyone — use PolicyExceptions for the `cilium-system` pods that legitimately need `privileged: true`.
    4. **Image signature verification at scale**: Kyverno's `verifyImages` policy (with cosign) verifies every image pull against a public key. The verification adds ~100ms to pod scheduling. For clusters with hundreds of pod starts per second, verify the signing verification overhead is acceptable — cache the results in the Kyverno OCI cache.
    5. **Policy drift detection**: Kyverno's background scan generates `PolicyReport` and `ClusterPolicyReport` objects with violation counts. Expose these to Grafana via the policy-reporter sidecar. A dashboard showing violation counts per namespace and per policy gives the platform team real-time visibility into compliance posture.

!!! success "Chapter 22 checklist"
    - Kyverno installed; core policies as code in Git (validate/mutate/generate).
    - **Validate**: no `:latest`, images only from the internal registry, limits required.
    - **Mutate**: secure defaults (seccomp, labels) injected automatically.
    - **Generate**: default-deny NetworkPolicy created for every new namespace.
    - Every policy rolled out **Audit → Enforce**; violations tracked in PolicyReports.

---
