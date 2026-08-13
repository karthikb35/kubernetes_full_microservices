## <a name="ch7a"></a>7A. Certificate & PKI Management

Chapter 7 gave TicketHub a browser-trusted certificate at the edge. But that public cert is the *tip* of a much larger iceberg: **a Kubernetes cluster is, from the first second of `kubeadm init`, a full Public Key Infrastructure.** Every control-plane component, every node, and every internal service proves who it is with an X.509 certificate. If those certificates are wrong, missing a name, or expired, the cluster doesn't "degrade" — it **stops**. This chapter is the complete picture: every certificate in the cluster, how HA multiplies them, how to inspect and renew them, and how to extend the same discipline to application-to-application traffic with an internal CA and mTLS.

### 7A.1 The cluster is a PKI — the certificate inventory

`kubeadm init` doesn't just start pods; it stands up **three independent Certificate Authorities** plus a token-signing keypair, then issues a leaf certificate to every identity that needs one. Everything lives under `/etc/kubernetes/pki` on each control-plane node.

![Cluster PKI hierarchy](assets/diagrams/07b-pki-hierarchy.png)

| CA (root of trust) | Signs certificates for | Why it's separate |
|--------------------|------------------------|-------------------|
| **kubernetes-ca** (`ca.crt`) | apiserver serving, apiserver→kubelet client, kubelet client/serving, admin, controller-manager, scheduler | The cluster's main identity domain |
| **etcd-ca** (`etcd/ca.crt`) | etcd server, etcd peer, etcd healthcheck-client, apiserver→etcd client | etcd is the crown jewels; its own CA limits blast radius |
| **front-proxy-ca** | front-proxy-client | Isolates the API aggregation layer (extension API servers) |
| **SA signing keypair** (`sa.key`/`sa.pub`) | *Not X.509* — signs ServiceAccount **JWTs** | Token signing, not TLS identity (Chapter 19) |

The individual leaf certificates every cluster has:

| Certificate | Identity it proves | Key SAN / subject |
|-------------|-------------------|-------------------|
| `apiserver.crt` | The API server **to clients** | VIP, every CP host, `kubernetes.default`, service IP |
| `apiserver-kubelet-client.crt` | API server **to each kubelet** | CN in `system:masters` |
| `apiserver-etcd-client.crt` | API server **to etcd** | client auth |
| `etcd/server.crt` | An etcd member **to its clients** | that member's IP + `localhost` |
| `etcd/peer.crt` | An etcd member **to other members** | that member's IP + host |
| `kubelet.crt` (per node) | A kubelet **to the API server** | `system:node:<host>`, group `system:nodes` |
| `front-proxy-client.crt` | The aggregation layer | client auth |
| `admin.conf` cert | Your `kubectl` **break-glass** identity | `system:masters` |

!!! key "Two ways to prove identity, one PKI"
    Every arrow between components in Kubernetes is **mutual TLS already** — the client
    presents a cert, the server presents a cert, and each validates the other against the
    right CA. The API server is the hub: it is a **TLS server** to kubectl and kubelets,
    and a **TLS client** to etcd and the kubelets. Get the CA trust and the SANs right and
    the whole mesh "just works"; get them wrong and nothing connects.

### 7A.2 HA multiplies the certificates — SANs, the VIP & the etcd mesh

A single-node control plane has one of each cert. **TicketHub's HA control plane has three** (Chapter 3: `cp-1/2/3` behind the HAProxy **VIP**). HA doesn't share leaf certs — each node generates **its own** apiserver/etcd certs, all signed by the **shared CAs** that `--upload-certs` distributes at join time. Two things must be correct for HA to work:

**1. The apiserver serving cert must carry every name a client might use.** A client can hit any CP node *or* the VIP, so the `apiserver.crt` **Subject Alternative Names** must include all of them. Miss the VIP and every `kubectl` through the load balancer fails TLS verification:

```yaml
# repo/cluster/kubeadm-config.yaml  — apiServer.certSANs feed apiserver.crt
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
controlPlaneEndpoint: "10.10.0.10:6443"     # the HAProxy VIP (Chapter 3)
apiServer:
  certSANs:
    - "10.10.0.10"          # VIP  <-- the one everyone forgets
    - "api.tickethub.internal"   # stable DNS for the VIP
    - "cp-1"
    - "cp-2"
    - "cp-3"
    - "10.10.0.11"          # cp-1 IP
    - "10.10.0.12"          # cp-2 IP
    - "10.10.0.13"          # cp-3 IP
etcd:
  local:
    serverCertSANs: ["10.10.0.11", "10.10.0.12", "10.10.0.13"]
    peerCertSANs:   ["10.10.0.11", "10.10.0.12", "10.10.0.13"]
```

**2. etcd is a 3-member mesh, and every member authenticates every other.** Each etcd `peer.crt` is used for **both** client and server auth (a member is both when replicating), and its SANs must list that member's address. The three peers form a fully-authenticated quorum; lose the peer certs and the Raft cluster (Chapter 3) can't form.

![HA control-plane certificates](assets/diagrams/07b-ha-certs.png)

!!! warning "The single most common HA cluster outage: a missing VIP SAN"
    If you add the load-balancer VIP or its DNS name *after* `kubeadm init`, the existing
    `apiserver.crt` won't include it and every call through the LB fails with
    `x509: certificate is valid for <hosts>, not <vip>`. Fixing it means regenerating the
    apiserver cert on **all three** nodes (`kubeadm certs renew apiserver` after adding the
    SAN to the config) and restarting each apiserver. Put every name in `certSANs`
    **before** you init.

### 7A.3 Inspecting & verifying what you have

You cannot manage what you cannot see. Two commands answer "what certs exist, and are they valid?"

```bash
# The whole inventory, expiry dates, and which CA signed each — run on every CP node.
kubeadm certs check-expiration
# CERTIFICATE                EXPIRES                  RESIDUAL TIME   EXTERNALLY MANAGED
# apiserver                  Aug 11, 2027 09:00 UTC   364d            no
# apiserver-etcd-client      Aug 11, 2027 09:00 UTC   364d            no
# etcd-peer                  Aug 11, 2027 09:00 UTC   364d            no
# ...
# CERTIFICATE AUTHORITY      EXPIRES                  RESIDUAL TIME
# ca                         Aug 09, 2035 09:00 UTC   9y

# Read one cert's SANs directly — confirm the VIP is really in there.
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -text \
  | grep -A1 "Subject Alternative Name"
# DNS:kubernetes, DNS:api.tickethub.internal, ..., IP Address:10.10.0.10
```

!!! key "Leaf certs are short-lived (1 year); CAs are long-lived (10 years)"
    `kubeadm` issues component leaf certs with a **1-year** lifetime and the CAs with a
    **10-year** lifetime. That asymmetry is deliberate: renewing a leaf is cheap and
    routine; rotating a CA is rare and disruptive (every kubeconfig and kubelet must learn
    the new trust anchor). Plan for leaf renewal as a **calendar event**, not an emergency.

### 7A.4 Renewal & rotation — the day-2 job that prevents outages

**Leaf renewal (routine).** Every `kubeadm upgrade apply` **auto-renews all control-plane leaf certs** — so a cluster upgraded at least yearly rarely expires. To renew out-of-band, do it **one control-plane node at a time** (HA lets the other two serve while you restart one):

```bash
# On each CP node in turn:
kubeadm certs renew all              # re-signs every leaf from the existing CA
# restart the control-plane static pods so they load the new certs:
kubectl -n kube-system delete pod \
  kube-apiserver-$(hostname) kube-controller-manager-$(hostname) \
  kube-scheduler-$(hostname) etcd-$(hostname)
kubeadm certs check-expiration       # confirm fresh 1-year dates
```

**Kubelet rotation (automatic).** Kubelets rotate their **client** cert automatically via the CSR API (`rotateCertificates: true`, auto-approved by the controller-manager). Turn on **serving**-cert rotation too (`serverTLSBootstrap: true`) so kubelet serving certs are CSR-issued and rotated instead of self-signed — then approve or auto-approve those CSRs.

**Expiry monitoring (non-negotiable).** Tie certificates into Chapter 26: run the **x509-certificate-exporter** to surface every cert's expiry as a Prometheus metric and **alert weeks ahead** — on all three CP nodes.

```yaml
# repo/manifests/70-observability/cert-expiry-rule.yaml
- alert: ControlPlaneCertExpiringSoon
  expr: (x509_cert_not_after - time()) / 86400 < 21   # < 3 weeks left
  for: 1h
  labels: { severity: page }
  annotations: { summary: "A control-plane certificate expires in under 21 days" }
```

!!! warning "Expired control-plane certs are a full outage, not a warning"
    If `apiserver.crt` or the etcd certs expire, the API server and etcd **refuse to
    start** — you cannot `kubectl` your way out, because kubectl itself needs a valid cert.
    Recovery is manual, on-console, per node. This is the one PKI failure that takes the
    whole cluster down at once, so the exporter alert above is mandatory, and CA-expiry
    (the 10-year clock) belongs in your team's long-term calendar.

### 7A.5 Application PKI — cert-manager as an internal CA

Chapter 7 used cert-manager with **Let's Encrypt** for the *public* edge. Internal service-to-service traffic is different: you don't want (or can't get) public certs for `orders.tickethub.svc`, and you don't want the internet in your trust path. The answer is to run **your own CA inside the cluster** with cert-manager — same automation, private trust.

![cert-manager internal CA](assets/diagrams/07b-internal-ca.png)

Bootstrap a root CA once (a self-signed issuer signs the root, which becomes a CA issuer that signs everything else):

```yaml
# repo/manifests/15-pki/internal-ca.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata: { name: selfsigned-root }
spec: { selfSigned: {} }
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata: { name: tickethub-root-ca, namespace: cert-manager }
spec:
  isCA: true
  commonName: tickethub-internal-ca
  secretName: tickethub-root-ca        # the CA key + cert land here
  duration: 87600h                     # 10 years, like the cluster CA
  privateKey: { algorithm: ECDSA, size: 256 }
  issuerRef: { name: selfsigned-root, kind: ClusterIssuer }
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata: { name: tickethub-internal }  # every service cert is issued by this
spec:
  ca: { secretName: tickethub-root-ca }
```

Now issue a certificate per service. **HA is the interesting part:** all replicas of a Deployment sit behind one **Service DNS name**, so they **share one certificate** whose SAN is that Service name — every pod mounts the same Secret and that is correct, because clients dial the Service, not a pod. For a **StatefulSet**, where clients address *individual* pods (`orders-0.orders-headless...`), the cert must also carry **per-pod DNS SANs** (or a wildcard):

```yaml
# repo/manifests/15-pki/orders-internal-cert.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata: { name: orders-tls, namespace: tickethub }
spec:
  secretName: orders-tls               # mounted by ALL orders replicas
  duration: 2160h                      # 90 days; cert-manager auto-renews
  dnsNames:
    - orders.tickethub.svc.cluster.local          # the Service (covers every replica)
    - "*.orders-headless.tickethub.svc.cluster.local"  # per-pod names (StatefulSet HA)
  issuerRef: { name: tickethub-internal, kind: ClusterIssuer }
```

**Trust distribution — the other half.** A certificate is useless if peers don't trust the CA that signed it. Manually copying the CA into every namespace is exactly the toil cert-manager exists to kill, so use its companion **trust-manager** to publish the CA bundle as a ConfigMap into **every** namespace automatically:

```yaml
# repo/manifests/15-pki/trust-bundle.yaml
apiVersion: trust.cert-manager.io/v1alpha1
kind: Bundle
metadata: { name: tickethub-ca }
spec:
  sources:
    - secret: { name: "tickethub-root-ca", key: "tls.crt" }
  target:
    configMap: { key: "ca.crt" }       # appears as ConfigMap tickethub-ca in all namespaces
```

!!! key "Deployment replicas share a cert; StatefulSet pods often need their own SANs"
    The rule that trips people up: a **Service name** covers *all* replicas behind it, so a
    stateless Deployment's replicas correctly share **one** Secret. Only when clients
    connect to a **specific pod** — StatefulSet members like a Postgres primary or a Kafka
    broker (Chapter 14) — do you need **per-pod DNS SANs** (or a headless-service wildcard)
    so each pod can present a name that matches how it's addressed.

### 7A.6 mTLS between services — app-managed vs mesh-managed

With per-service certs and a distributed CA bundle, you can turn on **mutual TLS** east-west. Two paths, and the right choice depends on scale:

| Aspect | App-managed mTLS | Mesh-managed mTLS (Cilium / Istio) |
|--|------------------|-------------------------------------|
| **How** | Each app mounts its cert Secret + CA bundle and enforces client certs in code | A sidecar/eBPF layer wraps every connection transparently |
| **Identity** | The cert-manager Certificate per service | **SPIFFE** identity per workload, issued & rotated automatically |
| **Rotation** | cert-manager renews the Secret; app must reload | Fully automatic, seconds-scale, no app change |
| **Best for** | A handful of sensitive links | Cluster-wide zero-trust across many services |
| **HA behavior** | All replicas share the Service cert | Every pod gets its own rotating identity, automatically |

!!! success "Chapter 7A checklist"
    - **Cluster PKI inventory** understood; `kubeadm certs check-expiration` clean on all CP nodes.
    - `apiServer.certSANs` includes the **VIP + DNS + every CP host/IP**; etcd server/peer SANs per member.
    - Leaf renewal **automated via upgrades**; out-of-band renewal done **one CP node at a time**.
    - Cert **expiry exported to Prometheus** and alerted **weeks ahead** (Chapter 26); CA expiry on the long-term calendar.
    - **kubelet** client (and serving) cert rotation enabled.
    - Internal **CA ClusterIssuer** via cert-manager; **trust-manager** distributes the CA bundle to all namespaces.
    - Per-service certs cover the **Service DNS**; StatefulSets add **per-pod SANs**; all replicas share/trust correctly.
    - East-west **mTLS** via a mesh (SPIFFE, auto-rotating) or app-managed for sensitive paths — no plaintext for regulated traffic.

---
