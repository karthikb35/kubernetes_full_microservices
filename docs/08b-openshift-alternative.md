## <a name="ch8b"></a>8A. Alternative Platform Bring-Up — OpenShift

Chapters 5–8 built the platform **the hard way**: we bootstrapped Kubernetes with `kubeadm`, then bolted on a CNI (Cilium), load balancing (MetalLB), HTTP routing (Gateway API), PKI (cert-manager), and storage (Rook-Ceph) — each a separate install we chose, wired, and now own. That is the best way to *understand* a cluster.

This chapter shows the **same platform delivered a different way**: **Red Hat OpenShift**, a Kubernetes *distribution* that ships all of those pieces pre-integrated. It is an **alternative to Chapters 5–8**, not a replacement for the rest of the book — once the platform is up, the workloads (Part III onward) deploy almost unchanged.

!!! note "This is an alternative track"
    Nothing else in the repo depends on this chapter. If you are running the DIY stack
    from Chapters 5–8, skip this. If your organisation standardises on OpenShift, read
    this instead of 5–8 and then continue at Chapter 9.

### 8A.1 What we are doing "here" (the DIY stack, recap)

The bare-metal path assembles the platform from independent, best-of-breed parts:

![DIY stack vs OpenShift](assets/diagrams/08b-openshift-stack.png)

| Layer | DIY choice (Ch 5–8) | You own |
|-------|---------------------|---------|
| Bootstrap | `kubeadm` HA control plane (Ch 5) | etcd, certs, upgrades |
| Container runtime | containerd | node config |
| CNI | Cilium (eBPF) + Hubble (Ch 6) | install, upgrades, tuning |
| Load balancer | MetalLB L2 (Ch 7) | IP pools |
| HTTP routing | Cilium Gateway API (Ch 7) | Gateway/HTTPRoute |
| PKI | cert-manager (Ch 7b) | issuers |
| Storage | Rook-Ceph (Ch 8) | Ceph day-2 ops |

The upside is **total control and zero licensing cost**; the downside is **you are the integrator** — every upgrade, CVE, and compatibility matrix is yours.

### 8A.2 What OpenShift is

**OpenShift** is a Kubernetes distribution that pre-integrates the entire platform — installer, runtime, CNI, ingress, storage, registry, monitoring, RBAC hardening, and GitOps — behind one supported product.

!!! mental "Mental model — flat-pack vs a fitted kitchen"
    The DIY stack is a pile of **flat-pack furniture**: every part is high quality and you
    choose each one, but *you* assemble and guarantee it fits. OpenShift is a **fitted
    kitchen**: it arrives measured and installed, the appliances already talk to each
    other, and one vendor supports the whole thing. You trade some freedom for
    integration and a warranty.

The equivalents are one-to-one:

| Concern | DIY (this book) | OpenShift equivalent |
|---------|-----------------|----------------------|
| Installer | `kubeadm` + manual steps | `openshift-install` (IPI / UPI / Agent-based / Assisted / SNO) |
| Container runtime | containerd | **CRI-O** |
| CNI | Cilium eBPF | **OVN-Kubernetes** (Cilium also certified) |
| Network visibility | Hubble | **Network Observability Operator** |
| Load balancer | MetalLB | **MetalLB Operator** (bundled) |
| HTTP routing | Gateway API (HTTPRoute) | **Routes** (native) + Gateway API |
| PKI / TLS | cert-manager | **cert-manager Operator** + built-in serving certs |
| Storage | Rook-Ceph | **OpenShift Data Foundation** (Ceph) / LVM Operator |
| Pod hardening | PSA `restricted` | **SCC** (`restricted-v2`) |
| Policy | Kyverno | Kyverno *or* Red Hat **Advanced Cluster Security** |
| Runtime threat detection | Falco | Falco *or* **ACS** |
| GitOps delivery | Argo CD (Ch 28) | **OpenShift GitOps** (*is* Argo CD) |
| CI pipelines | GitHub Actions | **OpenShift Pipelines** (Tekton) *or* keep Actions |
| Image registry | GHCR | **internal registry** *or* keep GHCR |
| CLI | `kubectl` | `oc` (superset of `kubectl`) |

### 8A.3 Bring-up methods

OpenShift offers several installers; pick by environment:

| Method | Best for | How it provisions |
|--------|----------|-------------------|
| **IPI** (installer-provisioned) | Cloud / vSphere | Installer creates the VMs *and* the cluster |
| **UPI** (user-provisioned) | You pre-build the machines | You provide nodes; installer configures them |
| **Agent-based** | **Bare metal, disconnected** | Boot a generated ISO on each node — closest analog to our 12-VM scenario |
| **Assisted Installer** | Guided bare metal | Web UI at console.redhat.com drives it |
| **SNO** (single-node) | Edge / labs | One node runs control plane + workloads |

For the TicketHub bare-metal scenario (Chapter 2), the **Agent-based installer** is the direct replacement for the entire Chapter 5 kubeadm sequence.

### 8A.4 Bare-metal bring-up, end to end (Agent-based)

Where Chapter 5 was *prep every node → init → install CNI → join → label*, OpenShift compresses that into **two config files and one ISO** — the CNI, storage bootstrap, registry, and monitoring all come up as part of the install.

```yaml
# install-config.yaml — the cluster shape (analogous to kubeadm-config.yaml, Ch 5)
apiVersion: v1
metadata:
  name: tickethub
baseDomain: example.com
controlPlane:
  name: master
  replicas: 3                 # HA control plane, like our 3 stacked cp nodes
compute:
  - name: worker
    replicas: 3
networking:
  networkType: OVNKubernetes  # the CNI — no separate Cilium install step
  clusterNetwork:
    - cidr: 10.128.0.0/14      # pod CIDR (cf. Ch 4 network design)
  serviceNetwork:
    - 172.30.0.0/16
platform:
  none: {}                    # bare metal, no cloud provider
pullSecret: '{"auths": ...}'  # registry credentials
sshKey: 'ssh-ed25519 ...'
```

```yaml
# agent-config.yaml — the physical machines (their MACs, IPs, roles)
apiVersion: v1beta1
metadata:
  name: tickethub
rendezvousIP: 10.0.10.10
hosts:
  - hostname: master-0
    role: master
    interfaces:
      - name: eno1
        macAddress: 52:54:00:aa:bb:01
```

```bash
# Generate a bootable ISO, boot every node from it, then wait.
openshift-install agent create image --dir ./cluster
#  → cluster/agent.x86_64.iso   (write to USB / PXE / virtual media)

# Nodes boot, elect a bootstrap, form etcd + control plane, install OVN-Kubernetes,
# stand up the internal registry and monitoring — all automatically.
openshift-install agent wait-for install-complete --dir ./cluster
#  → console URL + kubeadmin password
```

That single flow replaces **Chapters 5, 6, and most of 7–8**: HA control plane (5), CNI (6), and the load-balancer/ingress plumbing (7) arrive together. Storage is then a one-click Operator (8A.6).

!!! key "The big difference: assembly vs installation"
    In Chapters 5–8 *you* are the integrator — you install and version each layer. With
    OpenShift the **distribution owns the integration**: one installer version pins a
    tested set of CNI, runtime, ingress, and monitoring together, and `oc adm upgrade`
    moves the whole stack at once.

### 8A.5 Storage, ingress, and security the OpenShift way

- **Storage (replaces Ch 8):** install the **OpenShift Data Foundation** Operator; it deploys Ceph (the same engine Rook manages) and gives you StorageClasses like `ocs-storagecluster-ceph-rbd`. Our PVCs (Chapter 14) just change their `storageClassName`.
- **Ingress (replaces Ch 7):** OpenShift ships a **Router** (HAProxy) and a first-class `Route` object. You can keep the Gateway API `HTTPRoute` from Chapter 12, or expose the gateway with a `Route`:

    ```yaml
    apiVersion: route.openshift.io/v1
    kind: Route
    metadata:
      name: tickethub
      namespace: tickethub
    spec:
      host: tickethub.example.com
      to: { kind: Service, name: gateway }
      port: { targetPort: 8080 }
      tls: { termination: edge }
    ```

- **Security (replaces PSA in Ch 20):** OpenShift uses **Security Context Constraints (SCCs)**. Because our workloads are already `runAsNonRoot`, drop `ALL` capabilities, set `seccompProfile: RuntimeDefault`, and never hardcode a UID, they satisfy the default **`restricted-v2`** SCC with no changes — the Chapter 20 hardening pays off directly here.

!!! warning "OpenShift assigns random UIDs"
    The `restricted-v2` SCC runs each project's pods as a **random high UID**, not the
    image's `USER`. Images must not assume UID 0 *or* a specific UID, and any writable
    path must be group-writable (`GID 0`). Our images already run non-root with a
    read-only root filesystem, so they comply — but a hardcoded `runAsUser: 1000` would
    be rejected. Prefer `runAsNonRoot: true` without a fixed UID on OpenShift.

### 8A.6 How TicketHub maps on — almost unchanged

The workloads from Part III onward need only small, mechanical adjustments:

| TicketHub artifact | On OpenShift |
|--------------------|-------------|
| Namespaces (Ch 9) | `oc new-project` creates a **Project** (a namespace + annotations) |
| Helm chart `repo/charts/tickethub` | Runs as-is — `helm install` or an Argo CD Helm source |
| Argo CD app-of-apps (Ch 28) | Install the **OpenShift GitOps** Operator; the same `Application` YAML applies |
| Gateway API `HTTPRoute` (Ch 12) | Keep it, or expose via a `Route` |
| Rook-Ceph StorageClass (Ch 8) | Point PVCs at an ODF StorageClass |
| PSA `restricted` (Ch 20) | Satisfied by the `restricted-v2` SCC automatically |
| Kyverno image verification (Ch 24) | Keep Kyverno, or use ACS/sigstore admission |
| CI promotion (Ch 28) | Unchanged — still pins signed digests into `values.yaml` |

!!! example "Deploying the same chart on OpenShift"
    ```bash
    oc new-project tickethub
    # Argo CD (OpenShift GitOps) renders the same Helm chart:
    oc apply -f repo/argocd/app-of-apps.yaml
    # …or install directly:
    helm upgrade --install tickethub repo/charts/tickethub -n tickethub
    ```

### 8A.7 Trade-offs — when to pick which

| | DIY stack (Ch 5–8) | OpenShift |
|--|--------------------|-----------|
| Cost | Free (self-support) | Subscription per node/core |
| Control | Total — swap any layer | Opinionated — vendor-chosen defaults |
| Integration effort | High (you assemble) | Low (pre-integrated) |
| Upgrades | Per-component, manual | One `oc adm upgrade` for the stack |
| Support | Community | Enterprise SLA |
| Learning value | **Highest** — you see every seam | Lower — seams are hidden |
| Resource footprint | Lean | Heavier (bundled operators) |

!!! question "Architect considerations"
    1. **Team size vs. platform ambition** — a small team shipping product usually wins
       with OpenShift (someone else owns the integration matrix); a platform team building
       differentiation may want the DIY control of Chapters 5–8.
    2. **Portability** — the Helm chart, Argo CD `Application`s, and every workload manifest
       in this repo are **vanilla Kubernetes** and run on both. Lock-in shows up only where
       you adopt OpenShift-specific objects (`Route`, `ImageStream`, `BuildConfig`) — use
       them deliberately.
    3. **Security posture** — OpenShift's `restricted-v2` SCC and integrated ACS give a
       strong default; the DIY stack reaches parity only after Chapters 19–24.
    4. **Disconnected/air-gapped** — the Agent-based installer and internal registry make
       OpenShift strong for regulated, offline environments; the DIY stack needs extra
       mirroring work.

!!! success "Chapter 8A checklist"
    - OpenShift **bundles** what Chapters 5–8 assemble by hand: installer, CRI-O, OVN CNI, MetalLB, Router, ODF storage, registry, monitoring, GitOps.
    - **Agent-based install** replaces the whole kubeadm sequence with two config files and one ISO.
    - **SCC `restricted-v2`** replaces PSA — our already-hardened pods comply unchanged.
    - The **Helm chart, Argo CD app-of-apps, and CI promotion all carry over** — workloads are portable.
    - Choose OpenShift for **integration + support**; choose DIY for **control + learning + zero licensing**.

---
