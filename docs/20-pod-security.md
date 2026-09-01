## <a name="ch20"></a>20. Pod Security Admission & SecurityContext Hardening

RBAC controls the API; this chapter controls **what a pod may do on the node**. A container that runs as root, mounts the host filesystem, or holds Linux capabilities is a breakout waiting to happen. **Pod Security Admission (PSA)** enforces baseline guardrails per namespace, and **SecurityContext** hardens each pod in depth.

### 20.1 Pod Security Admission — three levels per namespace

PSA is built into the API server. You label a namespace with one of three levels, and non-compliant pods are rejected (or warned) at admission.

![PSA levels](assets/diagrams/20-psa-levels.png)

| Level | Allows | Use in TicketHub |
|-------|--------|------------------|
| **privileged** | Everything | Only `security` ns (Falco needs host access) |
| **baseline** | Blocks known privilege escalations | `data` ns (DBs need a few extras) |
| **restricted** | Hardened: non-root, no caps, seccomp | All **app** namespaces |

```yaml
# already baked into repo/manifests/00-namespaces/namespaces.yaml (Ch 9)
metadata:
  name: tickethub
  labels:
    pod-security.kubernetes.io/enforce: restricted    # reject violations
    pod-security.kubernetes.io/warn: restricted       # warn on kubectl
    pod-security.kubernetes.io/audit: restricted       # log to audit
```

!!! mental "Mental model — building codes vs. a home inspection"
    PSA is the **building code** for a namespace: every pod must meet the standard to be
    admitted. SecurityContext (next) is how each pod **proves it's up to code** — non-root
    wiring, no dangerous tools, sealed windows. PSA is enforced at the door; SecurityContext
    is what you build into the pod.

### 20.2 The three enforcement modes

- **enforce** — reject violating pods (production).
- **warn** — allow but return a warning to `kubectl` (great for migration).
- **audit** — allow but record in the audit log.

!!! tip "Roll out restricted with warn/audit first"
    Flip a namespace to `warn: restricted` + `audit: restricted` *before* `enforce`. You
    see every violation without breaking running workloads, fix the manifests, then set
    `enforce`. Retrofitting `enforce` onto a live namespace blind is how you cause an outage.

### 20.3 SecurityContext — defense in depth per pod

The `restricted` level demands a hardened **securityContext**. Here is the TicketHub standard applied to every app pod:

![SecurityContext](assets/diagrams/20-securitycontext.png)

```yaml
# pod-level
securityContext:
  runAsNonRoot: true
  runAsUser: 65532
  fsGroup: 65532
  seccompProfile:
    type: RuntimeDefault
# container-level
containers:
  - name: orders
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
```

| Setting | Stops |
|---------|-------|
| `runAsNonRoot` / `runAsUser` | Running as uid 0 |
| `readOnlyRootFilesystem` | Tampering with the image at runtime |
| `allowPrivilegeEscalation: false` | `setuid`/`sudo`-style escalation |
| `capabilities: drop: [ALL]` | Raw sockets, mounting, ptrace, etc. |
| `seccompProfile: RuntimeDefault` | Dangerous syscalls |

!!! key "This pairs with the Dockerfile from Chapter 10"
    `readOnlyRootFilesystem: true` and `runAsNonRoot` only work if the **image** was built
    for it — a non-root `USER`, and any writable paths mounted as `emptyDir` volumes.
    Security is designed at build time (Ch 10) and *enforced* at admission (here). If the
    app needs to write, give it a mounted `emptyDir` at that path, not a writable rootfs.

```yaml
# writable scratch without a writable rootfs
volumeMounts:
  - { name: tmp, mountPath: /tmp }
volumes:
  - name: tmp
    emptyDir: {}
```

!!! warning "Never set privileged: true on an app pod"
    `privileged: true` disables essentially all isolation — the container can access host
    devices and is one step from owning the node. Reserve it for node-level agents (Falco,
    CNI) in dedicated namespaces, and gate even those with Kyverno (Chapter 22).


### 20.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Pod Security Admission (PSA) `warn` mode writes warnings to the API server response, not to the pod's logs or events** — operators using CI pipelines must parse `kubectl apply` stderr for `Warning: would violate PodSecurity` messages. Many CI systems suppress stderr by default, making PSA warn mode silently useless.
    - **`securityContext.readOnlyRootFilesystem: true`** prevents writes to the container's root filesystem, but tmpfs mounts (via `emptyDir: { medium: Memory }`) and volumeMounts are writable. An application that writes logs to `/tmp` must mount an `emptyDir` at `/tmp` explicitly or the container will crash.
    - **`capabilities.drop: [ALL]` without adding back `NET_BIND_SERVICE`**: if your container binds to port 80 or 443, dropping ALL capabilities prevents binding to privileged ports (< 1024). Either run on a non-privileged port (8080) — the correct approach — or add back `NET_BIND_SERVICE` only.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`privileged: true` bypasses ALL namespace isolation**: a privileged container can mount the host filesystem, load kernel modules, and escape the namespace entirely. It is equivalent to root on the host. Never use `privileged: true` in application pods; even Falco's DaemonSet uses a minimal set of capabilities instead.
    - **`runAsNonRoot: true` without a specific UID fails unexpectedly**: if the container image's `USER` directive sets UID 0 (root), the pod will fail with `container has runAsNonRoot and image has non-numeric user root`. Always pair `runAsNonRoot: true` with `runAsUser: <non-zero UID>` for deterministic behavior.
    - **PSA `enforce` on `kube-system` breaks cluster components**: `kube-system` pods (kube-proxy, Cilium) require privileged capabilities. Applying `restricted` policy to `kube-system` will block the CNI agent pods and crash the cluster. Never apply PSA enforcement to `kube-system`, `kube-public`, or any platform namespace without testing first.

!!! question "Architect Considerations"
    1. **PSA vs Kyverno for pod security**: PSA enforces three fixed policy levels (privileged, baseline, restricted) — no customization. Kyverno (Chapter 22) can express the same policies with custom carve-outs. For an enterprise platform, Kyverno gives the flexibility to say "allow this one specific privileged workload with an explicit exception" while PSA's `warn` mode acts as a safety net.
    2. **Seccomp profile selection**: the default Docker seccomp profile blocks ~300 dangerous syscalls. The Kubernetes `RuntimeDefault` seccomp profile is equivalent. For payments/security-critical pods, a custom seccomp profile that allows ONLY the syscalls the binary actually uses (generated with `strace` or `seccompgen`) provides tighter isolation.
    3. **Image UID/GID governance**: standardize on a non-root UID range for all team images (e.g., `1000-1999`). Add a Kyverno policy that rejects images claiming UID 0 at admission time. This prevents the "just run as root for local dev" habit from reaching production.
    4. **Privileged DaemonSets namespace segregation**: Falco, Cilium, and node-exporter require elevated privileges. Run them in a dedicated `security` or `monitoring` namespace with explicit PSA `privileged` label. Never co-locate privileged DaemonSets with application workloads in the same namespace.
    5. **Security context inheritance testing**: define a security context regression test suite that runs against every new container image: verify `runAsNonRoot`, `readOnlyRootFilesystem`, no `CAP_SYS_ADMIN`. Add this to your CI pipeline as a policy gate before images reach the registry.

!!! success "Chapter 20 checklist"
    - App namespaces enforce **PSA restricted**; `security` ns privileged, `data` ns baseline.
    - Rolled out via **warn/audit → enforce**, not blind.
    - Every app pod: **non-root, readOnlyRootFilesystem, drop ALL caps, no priv-escalation, seccomp**.
    - Writable paths provided via `emptyDir`, not a writable rootfs.
    - **No** `privileged: true` outside dedicated node-agent namespaces.

---
