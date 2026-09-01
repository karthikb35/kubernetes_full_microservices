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
# See: repo/manifests/ for the full manifest
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


### 19.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **RBAC is additive only** — you cannot explicitly deny a permission. If a user has a RoleBinding that grants `get pods` and another that grants `list pods`, they have both. The only way to "deny" access is to not grant it in the first place and remove all relevant bindings. This makes RBAC reasoning about "what CAN this principal NOT do?" difficult — enumerate permissions via `kubectl auth can-i --list --as <user>`.
    - **ServiceAccount tokens are long-lived by default in older Kubernetes versions**: before Kubernetes 1.22, SA tokens were stored as Secrets with no expiry. From 1.24+, the token projection mechanism creates short-lived tokens (1 hour) automatically. If you're running workloads on 1.21 or below, audit token expiry explicitly.
    - **`ClusterRoleBinding` to a namespaced `Role`** is not possible — a ClusterRoleBinding must reference a ClusterRole. However, a `RoleBinding` CAN reference a ClusterRole: this applies the ClusterRole's permissions only within the binding's namespace. Use this pattern to define roles once as ClusterRoles and bind them per-namespace.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`system:masters` group bypasses all RBAC**: adding a user to `system:masters` (e.g., in the kubeconfig generated by kubeadm) gives permanent cluster-admin with no way to revoke — RBAC cannot deny `system:masters`. Never distribute the admin kubeconfig; use OIDC + RoleBindings for human access.
    - **Operator service accounts with ClusterRole `*` verbs**: a hastily scaffolded operator that grants `verbs: ["*"]` on `resources: ["*"]` across `apiGroups: ["*"]` is a cluster takeover vector if the operator pod is compromised. Audit and scope every operator's RBAC at install time.
    - **`automountServiceAccountToken: true` is the default**: every pod gets a mounted SA token that can call the Kubernetes API. A compromised pod with the default SA can `kubectl get secrets -n kube-system` if the SA has even basic RBAC. Always set `automountServiceAccountToken: false` on SAs for workloads that don't need API access.

!!! question "Architect Considerations"
    1. **OIDC integration for human access**: kubeadm-generated certificates are fine for cluster bootstrap, but human access in production should use an OIDC provider (Dex, Keycloak, Azure AD) so that user identities are tied to corporate directory, sessions expire, and access can be revoked centrally.
    2. **Least-privilege service account design**: each microservice should have a dedicated ServiceAccount with only the permissions it actually uses. The `orders` service needs to read its own ConfigMaps; it does not need to list pods or create Secrets. Audit actual API calls with `kubectl auth can-i` and audit logs, then prune.
    3. **RBAC for namespace self-service**: a team that can create namespaces can also bind ClusterRoles within them — effectively elevating themselves. Restrict `namespace create` to platform admins and provide a namespace provisioning workflow (Argo CD ApplicationSet or a custom Kubernetes controller) that applies RBAC templates.
    4. **Aggregated ClusterRoles**: the `view`, `edit`, and `admin` ClusterRoles are aggregate roles that automatically include permissions from any ClusterRole with the matching aggregation label. When you install a new operator (e.g., cert-manager), its CRD views should be aggregated into the `view` role so developers can `kubectl get certificates` with their normal access.
    5. **Audit log analysis**: RBAC decisions are logged in the Kubernetes audit log. Use a tool like `rbac-police` or `audit2rbac` to analyze audit logs and identify over-privileged service accounts. Run this analysis quarterly.

!!! success "Chapter 19 checklist"
    - Every service runs under its **own ServiceAccount**, never `default`.
    - Roles grant **specific verbs on named resources**; no wildcards.
    - `automountServiceAccountToken: false` unless the pod calls the API.
    - **No** `cluster-admin` on workloads; human access is namespaced and least-privilege.
    - Permissions audited with `kubectl auth can-i`.

---
