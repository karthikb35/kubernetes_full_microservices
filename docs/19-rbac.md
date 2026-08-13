## <a name="ch19"></a>19. RBAC & Service Accounts — Least Privilege for Every Actor

Part V hardens TicketHub. Security starts with **who can do what**. **Role-Based Access Control (RBAC)** governs every request to the API server — human or workload. The guiding rule is **least privilege**: each actor gets exactly the permissions it needs, and nothing more.

### 19.1 The four RBAC objects

![RBAC model](assets/diagrams/19-rbac-model.png)

| Object | Answers | Scope |
|--------|---------|-------|
| **Role** | *what* verbs on *which* resources | One namespace |
| **ClusterRole** | same, cluster-wide or reusable | Cluster |
| **RoleBinding** | grant a Role to a subject | One namespace |
| **ClusterRoleBinding** | grant a ClusterRole cluster-wide | Cluster |

**Subjects** are `User`, `Group` (humans, from the auth layer), or `ServiceAccount` (workloads).

!!! mental "Mental model — keys and keyrings in a building"
    A **Role** is a **key** that opens specific doors (verbs on resources). A
    **RoleBinding** is handing that key to a **person or robot** (subject). A **Role** in
    one namespace is a key that only works on that floor; a **ClusterRole** works building-wide.
    RBAC is **additive** — there's no "anti-key". Default is deny-all; you only ever grant.

### 19.2 RBAC is additive and default-deny

There is **no deny rule** in RBAC. If no binding grants a permission, it's refused. This makes reasoning simple: permissions only ever accumulate from the bindings that name you.

```yaml
# repo/manifests/60-security/orders-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: orders-reader
  namespace: tickethub
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]       # read config only — no secrets, no write
```

### 19.3 Give every workload its own ServiceAccount

Every pod authenticates to the API server as a **ServiceAccount (SA)**. By default it's the namespace's `default` SA — a trap, because bindings on `default` leak to *every* pod. Give each service a **dedicated SA** with a minimal Role.

![ServiceAccount auth](assets/diagrams/19-serviceaccount.png)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orders-sa
  namespace: tickethub
automountServiceAccountToken: false   # only mount if the app truly calls the API
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: orders-reader-binding
  namespace: tickethub
subjects:
  - kind: ServiceAccount
    name: orders-sa
roleRef:
  kind: Role
  name: orders-reader
  apiGroup: rbac.authorization.k8s.io
```

```yaml
# in the Deployment pod spec
spec:
  serviceAccountName: orders-sa
```

!!! key "Turn off automount unless the pod calls the API"
    Most application pods never talk to the Kubernetes API — yet by default a token is
    mounted into every one, handing an attacker who lands in the container a credential.
    Set `automountServiceAccountToken: false` on the SA (or pod) unless the workload
    genuinely needs API access. Fewer tokens = smaller blast radius.

### 19.4 Auditing and avoiding over-permission

```bash
kubectl auth can-i --list --as=system:serviceaccount:tickethub:orders-sa -n tickethub
kubectl auth can-i delete secrets --as=system:serviceaccount:tickethub:orders-sa -n tickethub  # -> no
```

!!! warning "Never bind cluster-admin to a workload or humans by default"
    `cluster-admin` via a ClusterRoleBinding is god mode. A compromised pod with it owns
    the cluster. Avoid wildcard verbs (`["*"]`) and wildcard resources; scope Roles to
    named resources. Humans get narrow, namespaced roles; break-glass admin is separate,
    audited, and rarely used.

!!! success "Chapter 19 checklist"
    - Every service runs under its **own ServiceAccount**, never `default`.
    - Roles grant **specific verbs on named resources**; no wildcards.
    - `automountServiceAccountToken: false` unless the pod calls the API.
    - **No** `cluster-admin` on workloads; human access is namespaced and least-privilege.
    - Permissions audited with `kubectl auth can-i`.

---
