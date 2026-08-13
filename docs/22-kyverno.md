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
# repo/manifests/60-security/kyverno-disallow-latest.yaml
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
# repo/manifests/60-security/kyverno-default-securitycontext.yaml
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

!!! success "Chapter 22 checklist"
    - Kyverno installed; core policies as code in Git (validate/mutate/generate).
    - **Validate**: no `:latest`, images only from the internal registry, limits required.
    - **Mutate**: secure defaults (seccomp, labels) injected automatically.
    - **Generate**: default-deny NetworkPolicy created for every new namespace.
    - Every policy rolled out **Audit → Enforce**; violations tracked in PolicyReports.

---
