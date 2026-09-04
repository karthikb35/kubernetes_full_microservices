## <a name="ch7"></a>7. Load Balancing & Gateway API — MetalLB + Cilium

On a cloud, `Service type=LoadBalancer` magically provisions a real load balancer with a public IP. On **bare metal, nobody provides that** — the Service would sit forever in `<pending>`. **MetalLB** fills the gap, and the **Kubernetes Gateway API** (implemented here by **Cilium**) sits on top to do smart HTTP routing for TicketHub's many services.

!!! note "What changed in this edition — Ingress → Gateway API"
    Earlier versions of this chapter used a classic **NGINX Ingress**. TicketHub has
    since **migrated to the Kubernetes Gateway API**, the official successor to Ingress.
    Ingress is now feature-frozen upstream — no new capabilities are being added to it —
    and the whole ecosystem is moving to Gateway API. Section **7.6** explains the *why*,
    the *cons of Ingress*, and *how Gateway API resolves them* in plain terms. If you have
    only ever seen Ingress, read 7.6 first, then come back.

### 7.1 The problem MetalLB solves

```bash
kubectl get svc -n platform cilium-gateway-tickethub
# NAME                        TYPE           EXTERNAL-IP   ...
# cilium-gateway-tickethub    LoadBalancer   <pending>     <-- stuck forever on bare metal
```

MetalLB watches for `LoadBalancer` Services, **allocates an external IP** from a pool you define, and **advertises** it to your physical network so packets actually arrive.

![MetalLB architecture](assets/diagrams/07-metallb-arch.png)

| Component | Kind | Role |
|-----------|------|------|
| **controller** | Deployment | Allocates IPs from the pool to Services |
| **speaker** | DaemonSet | Advertises the IP (L2 ARP/NDP, or BGP) |

```yaml
# repo/manifests/10-platform/metallb-pool.yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: tickethub-pool
  namespace: metallb-system
spec:
  addresses:
    - 10.20.0.100-10.20.0.200      # the VLAN 20 range from Chapter 4
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement            # simplest mode; use BGPAdvertisement with a capable router
metadata:
  name: tickethub-l2
  namespace: metallb-system
spec:
  ipAddressPools: [tickethub-pool]
```

!!! warning "L2 mode is failover, not load-sharing"
    In **L2 mode**, one elected node answers ARP for a given IP — all traffic for that
    IP flows through that single node (fast failover if it dies, but no load
    distribution). For true multi-node balancing, use **BGP mode** and peer MetalLB
    speakers with your data-center router. Plan this with your network team early.

### 7.2 Why you still need a routing layer on top

MetalLB gives you an **IP**; it knows nothing about HTTP. Without a routing layer, every service needing external access would burn its own external IP and have no TLS or path routing. The **Gateway** consumes **one** MetalLB IP and routes by **host/path** to many services.

![Gateway traffic flow](assets/diagrams/07-ingress-flow.png)

!!! mental "Mental model — building receptionist"
    MetalLB is the **street address** of the building (a public IP). The **Gateway** is
    the **receptionist** inside: one desk, but it reads where each visitor wants to go
    (`/api`, `/search`, `/`) and directs them to the right office (Service) — while
    also checking their credentials (TLS). You need both: an address to be found, and
    a receptionist to route.

### 7.3 Installing the Cilium Gateway API (pinned to infra nodes)

We already run **Cilium** as the CNI (Chapter 6), and Cilium ships a built-in Gateway API implementation — so there is **no separate ingress controller to install**. We just enable the feature and let Cilium provision the data plane:

```bash
helm upgrade cilium cilium/cilium -n kube-system --reuse-values \
  --set gatewayAPI.enabled=true \                 # turn on the Gateway API controller
  --set gatewayAPI.hostNetwork.enabled=false \    # use a LoadBalancer Service (MetalLB)
  --set nodeSelector.pool=infra                    # keep edge components on the infra pool (Ch 3)
```

The Gateway API **CRDs** must exist first (they are *not* built into Kubernetes like Ingress is):

```bash
kubectl apply -f \
  https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
kubectl get gatewayclass          # cilium should show ACCEPTED=True
```

!!! warning "Gateway API is CRDs, not core — install them or nothing works"
    `Ingress` ships inside the Kubernetes API server. `Gateway`, `HTTPRoute`, and
    friends are **CRDs** you must install (and keep version-matched to your controller).
    A `Gateway` applied before the CRDs exist fails with `no matches for kind "Gateway"`.

### 7.4 The TicketHub Gateway + HTTPRoute objects

Where Ingress crammed *listeners, TLS, and routing* into one object, the Gateway API splits them by **owner**. The platform team owns the **Gateway** (the ports, the IP, the TLS cert); each app team owns its **HTTPRoute** (the paths and backends). Both live in the repo:

```yaml
# repo/manifests/10-platform/gateway-tickethub.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: tickethub
  namespace: tickethub
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod   # auto TLS (see 7.5)
spec:
  gatewayClassName: cilium                             # Cilium realises this as a LB Service
  listeners:
    - name: http                                        # :80 — ACME challenge + redirect
      protocol: HTTP
      port: 80
      hostname: tickethub.example.com
    - name: https                                       # :443 — TLS terminated here
      protocol: HTTPS
      port: 443
      hostname: tickethub.example.com
      tls:
        mode: Terminate
        certificateRefs: [{ kind: Secret, name: tickethub-tls }]
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: tickethub
  namespace: tickethub
spec:
  parentRefs: [{ name: tickethub, sectionName: https }]
  hostnames: [tickethub.example.com]
  rules:
    - matches: [{ path: { type: PathPrefix, value: /api } }]   # API Gateway service
      backendRefs: [{ name: gateway, port: 8080 }]
    - matches: [{ path: { type: PathPrefix, value: / } }]      # everything else -> frontend
      backendRefs: [{ name: frontend, port: 80 }]
```

```bash
kubectl get gateway,httproute -n tickethub
# NAME                                    CLASS    ADDRESS        PROGRAMMED
# gateway.../tickethub                    cilium   10.20.0.100    True
# NAME                                    HOSTNAMES
# httproute.../tickethub                  ["tickethub.example.com"]
```

!!! tip "The old `ingressClassName: nginx` is now `gatewayClassName: cilium`"
    The routing engine is selected on the **Gateway**, not scattered across each route.
    Swapping implementations (Cilium → Envoy Gateway → NGINX Gateway Fabric) is a
    one-line change on the Gateway; the `HTTPRoute` objects are portable and untouched.

### 7.5 Automatic TLS with cert-manager

That one annotation — `cert-manager.io/cluster-issuer: letsencrypt` — is doing a lot of quiet work. On its own, the Gateway declares it *wants* HTTPS on `tickethub.com` and expects the certificate in a Secret named `tickethub-tls`. But **nothing creates that Secret** unless something obtains a real, browser-trusted certificate. That something is **cert-manager**.

**cert-manager** is an operator (Chapter 25) that automates the whole certificate lifecycle: request, prove ownership, store, and **renew before expiry** — so no human ever copies a `.pem` file onto a server at 2am.

![cert-manager ACME flow](assets/diagrams/07-cert-manager.png)

Install it once, cluster-wide (it lives in the `platform` namespace, Chapter 9):

```bash
helm install cert-manager jetstack/cert-manager \
  -n platform --create-namespace \
  --set crds.enabled=true          # installs the Certificate/Issuer CRDs
```

Then define **where** certificates come from. A **ClusterIssuer** is a cluster-scoped recipe for talking to a Certificate Authority — here, **Let's Encrypt** over the **ACME** protocol:

```yaml
# repo/manifests/10-platform/cert-manager-issuers.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt                  # matches the Gateway annotation
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory   # production CA
    email: platform@tickethub.com                            # expiry warnings go here
    privateKeySecretRef: { name: letsencrypt-account-key }   # your ACME account key
    solvers:
      - http01:
          gatewayHTTPRoute:                                  # prove ownership via HTTP-01
            parentRefs:
              - { name: tickethub, namespace: tickethub, kind: Gateway, group: gateway.networking.k8s.io }
```

**How ownership is proven (the ACME challenge).** Let's Encrypt won't sign a cert for `tickethub.com` unless you prove you control it. The two common challenges:

| Challenge | How you prove control | When to use |
|-----------|----------------------|-------------|
| **HTTP-01** | cert-manager serves a token at `http://tickethub.com/.well-known/...`; the CA fetches it | Public HTTP reachable (our case) |
| **DNS-01** | cert-manager writes a `TXT` DNS record the CA checks | Wildcards (`*.tickethub.com`) or no inbound HTTP |

The end-to-end loop, all automatic:

1. You apply the Gateway with the `cluster-issuer` annotation.
2. cert-manager notices and creates a **Certificate** object for the TLS hosts.
3. It requests the cert from Let's Encrypt and solves the **HTTP-01** challenge (temporarily attaching an HTTPRoute for `/.well-known/acme-challenge/...` to the Gateway's `:80` listener).
4. Let's Encrypt signs; cert-manager writes the cert + key into the **`tickethub-tls`** Secret.
5. The Gateway picks up the Secret and serves **HTTPS**. cert-manager renews ~30 days before the 90-day expiry — untouched by humans.

**Watching a certificate actually get generated.** "Automatic" doesn't mean "invisible" — cert-manager builds a chain of objects you can watch and, when something's wrong, debug. Each `Certificate` spawns a `CertificateRequest`, which spawns an ACME `Order`, which spawns a `Challenge`:

```text
Gateway -> Certificate -> CertificateRequest -> Order -> Challenge -> Secret (tickethub-tls)
```

Apply the Gateway, then follow the chain to completion:

```bash
# 1. The Certificate starts NOT ready while issuance runs.
kubectl get certificate -n tickethub
# NAME            READY   SECRET          AGE
# tickethub-tls   False   tickethub-tls   5s

# 2. Watch the request/order/challenge objects cert-manager created.
kubectl get certificaterequest,order,challenge -n tickethub

# 3. Follow the HTTP-01 challenge until the CA authorizes the domain.
kubectl describe challenge -n tickethub
# Status:  valid
# Reason:  Successfully authorized domain "tickethub.com"

# 4. READY flips to True; the Secret now holds the signed cert + key.
kubectl get certificate -n tickethub
# tickethub-tls   True    tickethub-tls   90s
kubectl get secret tickethub-tls -n tickethub -o jsonpath='{.type}'   # kubernetes.io/tls
```

!!! warning "If a cert is stuck, walk the chain downward — the failing object holds the reason"
    A `Certificate` stuck `READY: False` for minutes means a step below it failed. Run
    `kubectl describe` down the chain — **Certificate -> CertificateRequest -> Order ->
    Challenge** — and read the **Events/Status** of the *lowest* object; that's where the
    real error is. The usual culprits, all on the **HTTP-01** step: the DNS `A` record
    doesn't point at the MetalLB Gateway IP yet, **port 80 is blocked** (the CA fetches the
    token over plain HTTP before HTTPS exists), or you hit a Let's Encrypt **rate limit**
    (use staging). If you install the `cmctl` plugin, `cmctl status certificate
    tickethub-tls -n tickethub` prints the whole chain and its errors in one view.

!!! warning "Use the staging issuer first — Let's Encrypt rate-limits hard"
    Production Let's Encrypt allows only a handful of certs per domain per week. A
    misconfigured issuer can **burn your weekly quota** in minutes and lock you out.
    Always validate against the **staging** CA
    (`https://acme-staging-v02.api.letsencrypt.org/directory`) first — it issues
    **untrusted** certs (browser warning) but has generous limits — then flip the
    annotation to the production issuer once the flow works end-to-end.

!!! mental "Mental model — a robotic notary on a subscription"
    Manually managing TLS is a chore: buy a cert, prove you own the domain, install it,
    and diary a reminder to redo it before it expires. cert-manager is a **robotic
    notary**: it does the ownership proof, files the paperwork, installs the certificate
    where the Gateway expects it, and renews the subscription automatically — forever.

!!! note "This is only the public edge — the cluster has a much larger PKI"
    The Let's Encrypt cert here secures the *front door*. Behind it, every control-plane
    component, node, and (optionally) internal service also runs on certificates. For the
    complete picture — the cluster PKI inventory, HA certificate SANs for a 3-node control
    plane, renewal/rotation, and an **internal CA with cert-manager for service mTLS** —
    see **Chapter 7A, Certificate & PKI Management**.

### 7.6 Why we migrated from Ingress to the Gateway API

If you have only ever used **Ingress**, this section is for you. It explains — in plain
terms — what Ingress is, where it hurts, and how the **Gateway API** fixes each pain point.
This is the reasoning behind the migration you see in this chapter.

**What Ingress was.** An `Ingress` is a single Kubernetes object that says “expose these
HTTP paths on this hostname with this TLS cert.” It was the standard way to get traffic
into a cluster for years. It works — but it was designed early, kept deliberately minimal,
and is now **feature-frozen**: the Kubernetes project has stopped adding capabilities to it
and points everyone at the Gateway API instead. “Deprecated in spirit” is a fair summary —
Ingress still runs, but it is a dead-end road.

#### The cons of Ingress (why it hurts in practice)

| Problem with Ingress | What it means for a fresh grad | Consequence |
|---|---|---|
| **One object, mixed owners** | Listeners, TLS, *and* routing are all crammed into one `Ingress`. The platform team (who owns TLS/IP) and the app team (who owns paths) must edit the **same file**. | Change collisions, unclear ownership, risky reviews. |
| **Annotation soup** | Anything beyond basic path routing — rewrites, timeouts, rate limits, header matching, canary splits — lives in `nginx.ingress.kubernetes.io/...` **annotations**: free-form strings, not validated fields. | A typo in an annotation fails silently. Your YAML is **locked to one controller** (NGINX annotations don't work on Traefik/HAProxy). |
| **No portability** | Because behaviour hides in vendor annotations, moving from NGINX to another controller means rewriting them all. | Vendor lock-in; migrations are painful. |
| **Weak expressiveness** | Ingress natively understands host + path only. Header/method-based routing and traffic splitting (blue-green, canary) are not first-class. | You bolt on service meshes or CRDs to do routine things. |
| **Shared-fate reloads** | Classic controllers render **one big config** for all Ingresses. One bad Ingress can break the config reload for everyone. | A single team's mistake can take down unrelated services. |
| **Frozen** | No new features are being added upstream. | You are investing in a technology with no future roadmap. |

#### How the Gateway API resolves each one

| Gateway API answer | How it fixes the Ingress con |
|---|---|
| **Role-oriented objects** — `GatewayClass` (infra provider), `Gateway` (platform team: ports, IP, TLS), `HTTPRoute` (app team: paths, backends). | Ownership is split cleanly across separate objects and RBAC. Teams stop editing each other's files. |
| **Typed spec fields**, not annotations — header matches, method matches, redirects, traffic splitting, timeouts are **real, validated fields** in the CRD. | The API server rejects mistakes; behaviour is portable across implementations. |
| **Portable & implementation-agnostic** — selecting the engine is one line (`gatewayClassName`). Cilium, Envoy Gateway, Istio, NGINX Gateway Fabric all read the *same* `HTTPRoute`. | Swapping controllers no longer means rewriting routes. |
| **Rich routing built in** — weighted `backendRefs` (canary), header/method matches, request mirroring, redirects. | Common patterns need no annotations or extra CRDs. |
| **Per-route objects** — each `HTTPRoute` is independent; a broken one affects only itself. | One team's mistake no longer risks the whole edge. |
| **The active standard** — Gateway API is where all new investment goes; it also unifies mesh (east-west) routing under GAMMA. | You build on the technology with a future. |

!!! mental "Mental model — Ingress is a Swiss-army knife, Gateway API is a toolbox"
    **Ingress** is one folding tool: every blade crammed into a single handle that one
    person holds. Handy, but everyone fights over the handle and you can't add new blades.
    **Gateway API** is a labelled toolbox: the platform team owns the *box and the power
    outlet* (the `Gateway`), each app team grabs the *tool they need* (their `HTTPRoute`),
    and you can swap the whole brand of tools without changing how anyone works.

!!! warning "Migration gotchas — what actually bites during the switch"
    - **CRDs are not core.** `Ingress` lives inside the API server; `Gateway`/`HTTPRoute`
      are **CRDs** you must install *first* and keep version-matched to the controller.
    - **cert-manager solver changes.** The ACME HTTP-01 solver moves from
      `http01.ingress` to `http01.gatewayHTTPRoute`, and needs cert-manager's
      `ExperimentalGatewayAPISupport` (GA in recent releases) enabled at install.
    - **Annotations don't carry over.** Any `nginx.ingress.kubernetes.io/*` behaviour must
      be re-expressed as typed fields or filters — there is no automatic translation.
    - **Run both during cutover.** Keep the old Ingress and the new Gateway live on
      *different* hostnames/IPs, validate, shift DNS, then delete the Ingress. Don't flip
      in place.
    - **`Gateway` is namespaced but cross-namespace routing needs `ReferenceGrant`.** If an
      `HTTPRoute` in namespace A targets a Service in namespace B, you must grant it
      explicitly — a deliberate safety boundary Ingress never had.

!!! key "Layered edge: MetalLB → Gateway → Service → Pod"
    - **MetalLB** = L2/L3, gives bare metal a real external IP.
    - **Gateway (Cilium)** = L7, host/path routing + TLS termination, one IP for many services.
    - **Service** = stable virtual IP + DNS for a set of pods.
    - **Pod** = the actual workload.

    Each layer has one job; together they replace what a cloud LB + ALB gives you.


### 7.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - MetalLB in L2 mode announces the LoadBalancer IP from a **single node** at a time using ARP/NDP. Traffic arrives at that node, which then routes internally. This means a single node carries all north-south traffic — the load balancing happens AFTER the packet enters the cluster, not at the IP level. The announcing node becomes a bottleneck for very high-throughput services.
    - With **Cilium's Gateway API**, TLS is terminated inside the Cilium-managed Envoy proxy on the Gateway node — backend pods receive plain HTTP (or mTLS if you configure it separately). There is **no separate NGINX pod** to size; capacity is governed by the Cilium agent/Envoy resource limits on the infra nodes. Ensure they can absorb your peak TLS handshake rate.
    - `cert-manager` uses **ACME DNS-01 or HTTP-01 challenges** for Let's Encrypt. The HTTP-01 solver now attaches an **HTTPRoute** to the Gateway's `:80` listener rather than an Ingress. On a private on-prem cluster without internet access, HTTP-01 is impossible — use DNS-01 with your DNS provider's API, or an internal CA (Chapter 7A) for cluster-internal certificates.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **MetalLB pool overlapping with DHCP range**: if your data center DHCP server allocates IPs in the `10.10.0.200-250` range, ARP conflicts will cause intermittent LoadBalancer IP unreachability. Co-ordinate with the network team and document the reserved range.
    - **Gateway API CRDs missing or version-skewed**: unlike Ingress, `Gateway`/`HTTPRoute` are CRDs. Applying a `Gateway` before the CRDs exist fails with `no matches for kind "Gateway"`; a CRD version newer than the Cilium controller understands leaves the Gateway `PROGRAMMED: False` with no traffic. Install the CRDs first and match versions.
    - **Forgetting `parentRefs`/`sectionName`**: an `HTTPRoute` that doesn't reference the Gateway (or references the wrong listener section) is silently ignored — the modern equivalent of the old `ingressClassName` mismatch. Check `kubectl describe httproute` for an `Accepted: True` condition.
    - **cert-manager CRD version drift**: `Certificate`, `Issuer`, and `ClusterIssuer` CRDs are versioned. Upgrading cert-manager without reading the migration guide can cause CRD schema validation failures that block certificate renewals silently.

!!! question "Architect Considerations"
    1. **Single vs multi-Gateway**: running one `Gateway` for all traffic makes it a shared-fate component. Because `HTTPRoute`s are independent per-route objects, a bad route no longer breaks the whole edge — but the listeners/IP are still shared. Consider per-team or per-tier `Gateway`s (each its own IP) for strong isolation.
    2. **MetalLB BGP upgrade path**: L2 mode is simpler but has a single-node bottleneck. If north-south throughput requirements grow (>10 Gbps), plan the migration to BGP mode with ECMP — this requires network team involvement and a BGP router change.
    3. **WAF placement**: with Cilium's Gateway you can attach L7 policy/filters at the edge, or run a dedicated WAF. For a payments platform, should WAF rules live at the Gateway (easier), at the API Gateway service (more context-aware), or both? Layer 7 inspection adds latency — measure before committing.
    4. **Gateway API maturity by feature**: core `HTTPRoute` is GA, but some pieces (TLSRoute, GRPCRoute, mesh/GAMMA) are at different stability levels across implementations. Pin to the feature set your controller (Cilium) supports as GA, and track the conformance matrix before relying on experimental fields.
    5. **Certificate wildcard vs per-service**: a `*.tickethub.io` wildcard cert simplifies management but must be rotated for every domain — including unrelated ones. Per-service certs (automated by cert-manager) are noisier but limit blast radius if a cert is compromised.

!!! success "Chapter 7 checklist"
    - **MetalLB** installed with an **IPAddressPool** from the VLAN-20 range.
    - **Gateway API CRDs** installed and version-matched to the Cilium controller.
    - **Cilium Gateway API** enabled, pinned to the **infra** pool; the Gateway's LoadBalancer Service got a MetalLB IP.
    - A **Gateway** + **HTTPRoute** route `/api` and `/` with TLS terminated at the `:443` listener.
    - **cert-manager** installed with a **ClusterIssuer** using the `gatewayHTTPRoute` solver; TLS auto-issued and auto-renewed.
    - Validated against the **staging** ACME CA before flipping to production.
    - Decided **L2 vs BGP** mode with the network team.

---
