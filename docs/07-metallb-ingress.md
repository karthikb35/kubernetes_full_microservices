## <a name="ch7"></a>7. Load Balancing & Ingress — MetalLB + NGINX

On a cloud, `Service type=LoadBalancer` magically provisions a real load balancer with a public IP. On **bare metal, nobody provides that** — the Service would sit forever in `<pending>`. **MetalLB** fills the gap, and **NGINX Ingress** sits on top to do smart HTTP routing for TicketHub's many services.

### 7.1 The problem MetalLB solves

```bash
kubectl get svc -n platform ingress-nginx-controller
# NAME                       TYPE           EXTERNAL-IP   ...
# ingress-nginx-controller   LoadBalancer   <pending>     <-- stuck forever on bare metal
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

### 7.2 Why you still need Ingress on top

MetalLB gives you an **IP**; it knows nothing about HTTP. Without Ingress, every service needing external access would burn its own external IP and have no TLS or path routing. **NGINX Ingress** consumes **one** MetalLB IP and routes by **host/path** to many services.

![Ingress traffic flow](assets/diagrams/07-ingress-flow.png)

!!! mental "Mental model — building receptionist"
    MetalLB is the **street address** of the building (a public IP). NGINX Ingress is
    the **receptionist** inside: one desk, but it reads where each visitor wants to go
    (`/api`, `/search`, `/`) and directs them to the right office (Service) — while
    also checking their credentials (TLS). You need both: an address to be found, and
    a receptionist to route.

### 7.3 Installing NGINX Ingress (pinned to infra nodes)

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx \
  -n platform --create-namespace \
  --set controller.service.type=LoadBalancer \          # MetalLB assigns the IP
  --set controller.nodeSelector.pool=infra \            # run on infra pool (Ch 3)
  --set controller.tolerations[0].key=infra \
  --set controller.tolerations[0].effect=NoSchedule
```

### 7.4 The TicketHub Ingress object

One declarative object expresses all external routing and TLS:

```yaml
# repo/manifests/10-platform/ingress-tickethub.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tickethub
  namespace: tickethub
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt        # auto TLS (see 7.5)
    nginx.ingress.kubernetes.io/rate-limit-rps: "100"  # basic edge protection
spec:
  ingressClassName: nginx
  tls:
    - hosts: [tickethub.com, www.tickethub.com]
      secretName: tickethub-tls
  rules:
    - host: tickethub.com
      http:
        paths:
          - path: /api                       # API Gateway
            pathType: Prefix
            backend: { service: { name: gateway, port: { number: 80 } } }
          - path: /search
            pathType: Prefix
            backend: { service: { name: search, port: { number: 80 } } }
          - path: /                          # everything else -> frontend UI
            pathType: Prefix
            backend: { service: { name: frontend, port: { number: 80 } } }
```

```bash
kubectl get ingress -n tickethub
# NAME        CLASS   HOSTS                        ADDRESS        PORTS
# tickethub   nginx   tickethub.com,www...         10.20.0.100    80, 443
```

### 7.5 Automatic TLS with cert-manager

That one annotation — `cert-manager.io/cluster-issuer: letsencrypt` — is doing a lot of quiet work. On its own, the Ingress declares it *wants* HTTPS on `tickethub.com` and expects the certificate in a Secret named `tickethub-tls`. But **nothing creates that Secret** unless something obtains a real, browser-trusted certificate. That something is **cert-manager**.

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
  name: letsencrypt                  # matches the Ingress annotation
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory   # production CA
    email: platform@tickethub.com                            # expiry warnings go here
    privateKeySecretRef: { name: letsencrypt-account-key }   # your ACME account key
    solvers:
      - http01:
          ingress: { ingressClassName: nginx }               # prove ownership via HTTP-01
```

**How ownership is proven (the ACME challenge).** Let's Encrypt won't sign a cert for `tickethub.com` unless you prove you control it. The two common challenges:

| Challenge | How you prove control | When to use |
|-----------|----------------------|-------------|
| **HTTP-01** | cert-manager serves a token at `http://tickethub.com/.well-known/...`; the CA fetches it | Public HTTP reachable (our case) |
| **DNS-01** | cert-manager writes a `TXT` DNS record the CA checks | Wildcards (`*.tickethub.com`) or no inbound HTTP |

The end-to-end loop, all automatic:

1. You apply the Ingress with the `cluster-issuer` annotation.
2. cert-manager notices and creates a **Certificate** object for the TLS hosts.
3. It requests the cert from Let's Encrypt and solves the **HTTP-01** challenge (temporarily routing `/.well-known/acme-challenge/...` through the same NGINX Ingress).
4. Let's Encrypt signs; cert-manager writes the cert + key into the **`tickethub-tls`** Secret.
5. NGINX Ingress picks up the Secret and serves **HTTPS**. cert-manager renews ~30 days before the 90-day expiry — untouched by humans.

**Watching a certificate actually get generated.** "Automatic" doesn't mean "invisible" — cert-manager builds a chain of objects you can watch and, when something's wrong, debug. Each `Certificate` spawns a `CertificateRequest`, which spawns an ACME `Order`, which spawns a `Challenge`:

```text
Ingress -> Certificate -> CertificateRequest -> Order -> Challenge -> Secret (tickethub-tls)
```

Apply the Ingress, then follow the chain to completion:

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
    doesn't point at the MetalLB Ingress IP yet, **port 80 is blocked** (the CA fetches the
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
    where NGINX expects it, and renews the subscription automatically — forever.

!!! note "This is only the public edge — the cluster has a much larger PKI"
    The Let's Encrypt cert here secures the *front door*. Behind it, every control-plane
    component, node, and (optionally) internal service also runs on certificates. For the
    complete picture — the cluster PKI inventory, HA certificate SANs for a 3-node control
    plane, renewal/rotation, and an **internal CA with cert-manager for service mTLS** —
    see **Chapter 7A, Certificate & PKI Management**.

### 7.6 Ingress vs Gateway API (a forward note)

The newer **Gateway API** is the successor to Ingress — more expressive, role-oriented (separating infra vs app concerns), and better for multi-team clusters. Cilium can act as a Gateway API implementation. For TicketHub we use classic Ingress (mature, simple), but an architect should know Gateway API is where the ecosystem is heading.

!!! key "Layered edge: MetalLB → Ingress → Service → Pod"
    - **MetalLB** = L2/L3, gives bare metal a real external IP.
    - **Ingress (NGINX)** = L7, host/path routing + TLS termination, one IP for many services.
    - **Service** = stable virtual IP + DNS for a set of pods.
    - **Pod** = the actual workload.

    Each layer has one job; together they replace what a cloud LB + ALB gives you.

!!! success "Chapter 7 checklist"
    - **MetalLB** installed with an **IPAddressPool** from the VLAN-20 range.
    - **NGINX Ingress** installed, pinned to the **infra** pool, given a MetalLB IP.
    - A single **Ingress** object routes `/api`, `/search`, `/` with TLS.
    - **cert-manager** installed with a **ClusterIssuer**; TLS auto-issued and auto-renewed.
    - Validated against the **staging** ACME CA before flipping to production.
    - Decided **L2 vs BGP** mode with the network team.

---
