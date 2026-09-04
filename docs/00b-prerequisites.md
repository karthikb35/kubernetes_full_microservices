## <a name="ch0"></a>0. Prerequisites & a Five-Minute Primer

This book assumes only **basic Linux** and **"what a container is."** Everything else is
built up from first principles. But five ideas recur on almost every page — the
**declarative object model**, **kubectl/kubeconfig**, **Helm**, **CIDR notation**, and the
**stateful backends** (Postgres, Redis, Kafka). Rather than interrupt later chapters to
define them, we front-load them here. Skim this once; refer back whenever a term feels
assumed. A full **Glossary** sits at the back of the book (Appendix A).

### 0.1 Everything is a declarative object

You almost never *tell* Kubernetes to "do" something imperatively. Instead you **declare a
desired state** as a YAML object, hand it to the cluster, and a **controller** continuously
works to make reality match. This one idea underpins Deployments, Services, autoscaling,
GitOps — the whole book.

![The declarative control loop](assets/diagrams/00-object-anatomy.png)

Every Kubernetes object has the **same four-part shape**. Once you can read one, you can
read all of them:

```yaml
# See: repo/manifests/ for the full manifest
apiVersion: apps/v1        # which API group + version defines this kind
kind: Deployment           # the type of object
metadata:                  # name, namespace, labels — how it's identified
  name: catalog
  namespace: tickethub
spec:                      # DESIRED state — what YOU want (the only part you write)
  replicas: 3
status:                    # ACTUAL state — what IS (filled in by Kubernetes, read-only)
  readyReplicas: 3
```

| Field | Who writes it | Meaning |
|-------|---------------|---------|
| `apiVersion` | You | Which API group/version (e.g. `apps/v1`, `v1`, `networking.k8s.io/v1`) |
| `kind` | You | The object type (`Pod`, `Service`, `Deployment`, …) |
| `metadata` | You | Name, namespace, **labels** (key/value tags used everywhere) |
| `spec` | You | **Desired** state — your request |
| `status` | Kubernetes | **Actual** state — the controller's report back |

!!! mental "Mental model — a thermostat, not a light switch"
    A light switch is **imperative**: you flip it, the light obeys once. A thermostat is
    **declarative**: you set 21°C (the `spec`) and it *continuously* works to reach and
    hold it, compensating when a window opens. Kubernetes is a giant rack of thermostats.
    You declare `replicas: 3`; if a pod dies, a controller notices the gap between `spec`
    and `status` and starts a replacement — no command from you.

!!! key "Labels are the glue of the whole system"
    A **label** is a `key: value` tag in `metadata.labels` (e.g. `app: orders`). Services
    find pods by label, Deployments own pods by label, NetworkPolicies select pods by
    label, monitoring scrapes pods by label. When something "can't find" something else in
    later chapters, a **label/selector mismatch** is the first thing to check.

### 0.2 Talking to the cluster — kubectl, kubeconfig & contexts

`kubectl` is the command-line client. It never talks to nodes directly — it sends every
request to the **kube-apiserver**, the single front door. How does `kubectl` know *which*
cluster and *who you are*? A file called the **kubeconfig** (default `~/.kube/config`).

![How a request reaches the cluster](assets/diagrams/00-kubectl-auth.png)

A kubeconfig bundles three things into named **contexts** so you can switch clusters
instantly:

| Kubeconfig part | Holds |
|-----------------|-------|
| **cluster** | The API server URL (our VIP `https://10.10.0.10:6443`) + its CA cert |
| **user** | *Your* credentials — a client certificate or an OIDC token |
| **context** | A named pairing of (cluster + user + default namespace) |

```bash
kubectl config get-contexts          # list clusters you can reach
kubectl config use-context tickethub-prod
kubectl config set-context --current --namespace=tickethub   # stop typing -n
kubectl get pods                     # now scoped to tickethub
```

!!! key "Kubernetes has no 'User' object — identity comes from outside"
    This surprises everyone. You cannot `kubectl create user alice`. A **human identity**
    is proven to the API server one of two ways: a **client certificate** signed by the
    cluster CA, or an **OIDC token** from an external identity provider (Okta, Entra ID,
    Google). The API server only **authenticates** (verifies who you are) and then
    **authorizes** (RBAC, Chapter 19) — it never *stores* users. That's why Chapter 19's
    "subjects" are `User`/`Group` strings that come "from the auth layer": that layer is
    your certs or OIDC provider, not Kubernetes.

Every request the API server accepts passes three gates, in order — worth memorizing
because Chapters 19–22 each live at one of them:

1. **Authentication (authN)** — *who are you?* (client cert or OIDC token)
2. **Authorization (authZ)** — *are you allowed?* (**RBAC**, Chapter 19)
3. **Admission** — *is the object itself acceptable?* (**PSA**/**Kyverno**, Chapters 20, 22)

### 0.3 Helm in five minutes

Many platform components in this book (Cilium, the Cilium Gateway API, Falco, the Prometheus stack)
are installed with **Helm** — the Kubernetes package manager. You'll see `helm install …`
repeatedly, so here's the whole model:

| Helm term | Analogy | What it is |
|-----------|---------|------------|
| **Chart** | A software installer package | A bundle of templated YAML manifests |
| **Values** | The installer's settings screen | Your overrides (`--set key=value` or `values.yaml`) |
| **Release** | An installed program | One deployment of a chart into your cluster |
| **Repo** | An app store | A server hosting charts (`helm repo add …`) |

```bash
helm repo add cilium https://helm.cilium.io/        # register a chart source
helm install cilium cilium/cilium \                 # install chart -> named release "cilium"
  --namespace kube-system \
  --set kubeProxyReplacement=true                    # override a default value
helm upgrade cilium cilium/cilium --set hubble.ui.enabled=true   # change the release
helm list -A                                         # what's installed
```

!!! tip "Helm renders YAML, then applies it — nothing magic"
    A chart is just **templates + your values → plain Kubernetes YAML**, which Helm then
    applies like any manifest. Anything Helm installs, you can inspect with normal
    `kubectl get`. When a `--set` flag in this book looks mysterious, it's simply filling a
    blank in the chart's templates. `helm template …` prints the final YAML without
    installing — great for seeing exactly what you're about to get.

### 0.4 Reading IP addresses & CIDR notation

Chapter 4 plans four separate networks using notation like `10.244.0.0/16`. If the `/16`
is unfamiliar, here's all you need.

An IPv4 address is four bytes: `10.244.0.5`. The **`/N` suffix (the "prefix length")** says
how many leading bits are *fixed* as the network; the rest are free for hosts.

| CIDR | Fixed prefix | Usable-ish size | Reads as |
|------|--------------|-----------------|----------|
| `10.10.0.0/24` | first 24 bits | 256 addresses | "the `10.10.0.x` block" |
| `10.244.0.0/16` | first 16 bits | 65,536 addresses | "all `10.244.x.x`" |
| `10.96.0.0/12` | first 12 bits | ~1,048,576 | "`10.96.x.x`–`10.111.x.x`" |

!!! key "Smaller /N = bigger network"
    The number is *fixed bits*, so a **smaller** number means **fewer fixed bits** and a
    **larger** address range. `/16` (65k addresses) is far bigger than `/24` (256). The
    Pod CIDR is a `/16` because a cluster has *lots* of pods; a single VLAN is a `/24`.
    The one rule that matters for the whole book: these ranges must **never overlap**
    (Chapter 4).

### 0.5 The stateful backends — Postgres, Redis & Kafka

TicketHub's services are stateless, but they lean on three stateful backends the book
deploys as StatefulSets (Chapters 11, 14). You don't need to *operate* them expertly, but
you should know what each *is*.

| Backend | Category | One-line role | Why TicketHub uses it |
|---------|----------|---------------|-----------------------|
| **PostgreSQL** | Relational database (SQL) | Durable, transactional records | Users, catalog, orders, payments — the source of truth |
| **Redis** | In-memory key/value store | Very fast, short-lived data | Seat **holds** (expire in minutes), dedupe caches |
| **Kafka** | Distributed event log / message broker | Durable stream of **events** between services | Async fan-out: emails, search indexing, analytics |

**Kafka** deserves a few extra terms because Chapters 1, 16 and 26 use them:

| Kafka term | Meaning |
|------------|---------|
| **Topic** | A named stream of events (e.g. `ticket-events`) |
| **Broker** | One Kafka server node; a cluster has several for redundancy |
| **Producer / Consumer** | A service that *writes* / *reads* events |
| **Consumer group** | A set of consumer replicas sharing the work of one topic |
| **Lag** | How many events a consumer is **behind** — the backlog. KEDA scales on this (Chapter 16) |

!!! mental "Mental model — Kafka is a shared, replayable mailbox"
    A **synchronous** call (REST/gRPC) is a **phone call** — both parties must be present.
    Kafka is a **mailbox**: Orders drops a "ticket purchased" letter (**event**) into a
    **topic** and moves on. Notifications reads the mailbox whenever it's ready. If
    Notifications is down, letters wait; when it recovers it catches up on the **lag**.
    That decoupling is why a slow email provider can never fail a ticket sale.

### 0.6 A few kernel terms you'll meet at install time

Chapters 2 and 5 prepare Linux nodes and touch low-level terms. Quick definitions so the
install commands aren't black boxes (all also in the Glossary):

| Term | Plain meaning |
|------|---------------|
| **cgroup** | A Linux kernel feature that limits/accounts a process's CPU & memory. Requests/limits (Chapter 15) are enforced via cgroups |
| **cgroup driver** | *Who* manages cgroups — `systemd` or `cgroupfs`. containerd and kubelet must pick the **same** one or pods fail to start (Chapter 5) |
| **static pod** | A pod the kubelet runs directly from a file on the node (not from the API server). The control-plane components run this way (Chapter 5) |
| **network namespace** | A private network stack (its own interfaces/routes) that isolates a pod's networking |
| **veth pair** | A virtual "cable" — one end in the pod's namespace, one on the node — that the CNI creates to connect a pod to the network (Chapter 6) |


### 0.9 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - The **kubeconfig context** is not the same as a user account — it is a named combination of cluster, user credentials, and namespace. You can have many contexts pointing at the same cluster with different credentials; `kubectl config use-context` just changes which combination is active.
    - `kubectl` communicates only with the **kube-apiserver** — never with kubelets directly. Every operation (even `kubectl exec`) is proxied through the API server.
    - Helm charts are just **templates** that render to Kubernetes YAML. The actual objects live in the cluster; Helm tracks release state in a Secret in the same namespace. Deleting that Secret orphans the objects — `helm list` shows nothing but the resources still run.

!!! warning "Gotchas — traps that catch experienced engineers"
    - Confusing `kubectl apply` (declarative, idempotent, tracks last-applied-configuration annotation) with `kubectl create` (imperative, fails if the object already exists). Always prefer `apply` in automation.
    - Using `kubectl delete pod X` to "restart" a pod managed by a Deployment just causes the Deployment to create a replacement — the correct restart idiom is `kubectl rollout restart deployment/X`.
    - Assuming all objects are namespaced — `Node`, `PersistentVolume`, `ClusterRole`, `StorageClass`, and `CustomResourceDefinition` are **cluster-scoped**. Passing `-n my-ns` does nothing for them.

!!! question "Architect Considerations"
    1. **Single kubeconfig vs per-cluster** — should operators use a shared admin kubeconfig (simple but over-privileged) or per-person OIDC tokens (auditable, revokable)? Choose OIDC + `kubectl oidc-login` for any team larger than 2.
    2. **kubectl version skew** — the client must be within ±1 minor version of the server. Enforce this via a cluster-local `kubectl` wrapper script that pins the correct version.
    3. **Helm vs raw manifests** — Helm adds release lifecycle management but introduces template complexity. Use Helm for third-party software you consume; use raw manifests (or Kustomize) for your own services where you control the YAML.
    4. **etcd as the source of truth** — everything in `kubectl get` is a live read from etcd. There is no separate "config database" to sync; the cluster state IS the database.
    5. **Preview environments** — namespaces make cheap preview environments only if your storage (PVCs, secrets) can also be namespace-scoped and cheaply provisioned. Plan PVC provisioning speed before committing to PR-per-namespace patterns.

!!! success "Chapter 0 checklist — you're ready if you can say…"
    - Every object is `apiVersion` + `kind` + `metadata` + **`spec` (desired)** + `status` (actual).
    - `kubectl` talks to the **apiserver**; **kubeconfig** holds *which cluster* + *who you are*.
    - Kubernetes **doesn't store users** — identity is a client cert or OIDC token; RBAC authorizes.
    - **Helm** = charts (templated YAML) + values → a named **release**.
    - `/16` is **bigger** than `/24`; cluster CIDRs must never overlap.
    - **Postgres** = SQL truth, **Redis** = fast ephemeral, **Kafka** = durable event log (topics, lag).

    With the vocabulary in place, Part I begins the real work: designing TicketHub and the
    data center it will run on.

---
