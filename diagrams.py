"""
Mermaid diagram sources for the Kubernetes Architecture textbook, keyed by
output filename (no extension). Rendered to assets/diagrams/<key>.png.

A shared THEME + reusable classDef palette keeps every diagram visually
consistent and color-coded:
  users/clients -> blue     edge/ingress -> orange
  services      -> green    data stores  -> red
  platform/infra-> purple   async/events -> teal
"""

# Mermaid init directive: consistent fonts/colors across all diagrams.
T = (
    "%%{init: {'theme':'base','themeVariables':{"
    "'fontFamily':'Helvetica','fontSize':'16px',"
    "'primaryColor':'#e8f0fe','primaryTextColor':'#12325c',"
    "'primaryBorderColor':'#0b3d91','lineColor':'#64748b',"
    "'clusterBkg':'#f7f9fc','clusterBorder':'#c4ccd8'}}}%%\n"
)

# Reusable class palette appended to flowcharts.
PALETTE = """
classDef user fill:#dbeafe,stroke:#1d4ed8,stroke-width:2px,color:#1e3a8a;
classDef edge fill:#ffedd5,stroke:#c2410c,stroke-width:2px,color:#7c2d12;
classDef svc fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#14532d;
classDef data fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d;
classDef plat fill:#ede9fe,stroke:#6d28d9,stroke-width:2px,color:#4c1d95;
classDef evt fill:#ccfbf1,stroke:#0f766e,stroke-width:2px,color:#134e4a;
"""

DIAGRAMS: dict[str, str] = {}

# ===========================================================================
# CHAPTER 0 — Prerequisites & primer
# ===========================================================================

DIAGRAMS["00-object-anatomy"] = T + """
flowchart LR
  DEV["You write YAML<br/>spec = desired state"]:::user
  KC["kubectl apply"]:::edge
  API["kube-apiserver<br/>validate + store"]:::svc
  ETCD["etcd<br/>cluster database"]:::data
  CTRL["Controller<br/>reconcile loop"]:::plat
  NODE["kubelet on a node<br/>runs the pods"]:::svc
  DEV --> KC --> API --> ETCD
  ETCD --> CTRL
  CTRL -->|"diff spec vs status,<br/>then act"| NODE
  NODE -->|"reports status"| API
""" + PALETTE

DIAGRAMS["00-kubectl-auth"] = T + """
flowchart LR
  U["Human or app"]:::user
  CFG["kubeconfig<br/>cluster + creds + context"]:::edge
  subgraph API["kube-apiserver — every request passes 3 gates"]
    direction TB
    AUTHN["1. AuthN<br/>client cert / OIDC token"]:::plat
    AUTHZ["2. AuthZ<br/>RBAC (Ch 19)"]:::plat
    ADM["3. Admission<br/>PSA / Kyverno (Ch 20, 22)"]:::plat
    AUTHN --> AUTHZ --> ADM
  end
  ETCD["etcd"]:::data
  U --> CFG --> AUTHN
  ADM --> ETCD
""" + PALETTE

# ===========================================================================
# CHAPTER 1 — TicketHub scenario, service catalog, interactions
# ===========================================================================

DIAGRAMS["01-context"] = T + """
flowchart TB
  U["End users<br/>web + mobile"]:::user
  ADMIN["Event organizers<br/>admin portal"]:::user
  CDN["CDN / DNS<br/>(static assets, TLS)"]:::edge
  subgraph DC["On-prem Data Center - Kubernetes Cluster"]
    direction TB
    GW["Edge: Gateway API<br/>+ API Gateway svc"]:::edge
    APP["TicketHub microservices"]:::svc
    DATA["Stateful data plane<br/>Postgres - Redis - Kafka - Object store"]:::data
    GW --> APP --> DATA
  end
  PAY["External Payment<br/>Provider (Stripe)"]:::plat
  EMAIL["Email / SMS<br/>Provider (SendGrid)"]:::plat
  U --> CDN --> GW
  ADMIN --> CDN
  APP -->|"charge"| PAY
  APP -->|"send tickets"| EMAIL
""" + PALETTE

DIAGRAMS["01-microservices"] = T + """
flowchart TB
  subgraph EDGE["Edge / North-South"]
    ING["Cilium Gateway API"]:::edge
    GWSVC["API Gateway<br/>authN, routing, rate-limit"]:::edge
  end
  subgraph CORE["Core business services"]
    UI["Frontend UI<br/>(Next.js SSR)"]:::svc
    CAT["Catalog Service<br/>events and venues"]:::svc
    INV["Inventory Service<br/>seat and ticket holds"]:::svc
    ORD["Orders Service<br/>booking lifecycle"]:::svc
    PAY["Payments Service<br/>Stripe integration"]:::svc
    USR["Users / Auth Service<br/>accounts, JWT"]:::svc
    NOTIF["Notifications Service<br/>email and SMS"]:::svc
    SEARCH["Search Service<br/>event discovery"]:::svc
  end
  subgraph DATA["Data plane"]
    PG[("PostgreSQL<br/>per-service DBs")]:::data
    RD[("Redis<br/>cache and holds")]:::data
    KAF[["Kafka<br/>event bus"]]:::evt
    OBJ[("Object store<br/>Rook-Ceph S3")]:::data
  end
  ING --> GWSVC
  GWSVC --> UI
  GWSVC --> CAT & INV & ORD & PAY & USR & SEARCH
  UI --> GWSVC
  CAT --> PG
  INV --> RD
  ORD --> PG
  USR --> PG
  SEARCH --> OBJ
  ORD -. "publish OrderCreated" .-> KAF
  INV -. "publish SeatHeld" .-> KAF
  PAY -. "publish PaymentCaptured" .-> KAF
  KAF -. "consume" .-> NOTIF
  KAF -. "consume" .-> SEARCH
  NOTIF --> RD
""" + PALETTE

DIAGRAMS["01-sync-async"] = T + """
flowchart LR
  subgraph SYNC["Synchronous - request/response (REST + gRPC)"]
    direction LR
    C1["Client"]:::user --> G1["Gateway"]:::edge --> S1["Orders"]:::svc --> S2["Inventory"]:::svc
  end
  subgraph ASYNC["Asynchronous - event-driven (Kafka)"]
    direction LR
    S3["Orders"]:::svc -. "OrderCreated" .-> B["Kafka topic"]:::evt
    B -. "consume" .-> S4["Notifications"]:::svc
    B -. "consume" .-> S5["Search indexer"]:::svc
  end
  NOTE["Sync for user-facing reads/writes that need an immediate answer.<br/>Async for side-effects, fan-out, and decoupling (resilience)."]
""" + PALETTE

DIAGRAMS["01-booking-sequence"] = T + """
sequenceDiagram
  autonumber
  participant U as User
  participant GW as API Gateway
  participant ORD as Orders
  participant INV as Inventory
  participant PAY as Payments
  participant K as Kafka
  participant NOT as Notifications
  U->>GW: POST /orders (eventId, seats)
  GW->>ORD: create order (JWT verified)
  ORD->>INV: hold seats (gRPC)
  INV-->>ORD: seats held (TTL 10 min)
  ORD->>PAY: authorize payment
  PAY-->>ORD: payment captured
  ORD->>K: publish OrderConfirmed
  K-->>NOT: consume OrderConfirmed
  NOT-->>U: email tickets
  ORD-->>GW: 201 Created (orderId)
  GW-->>U: booking confirmed
""" 

DIAGRAMS["01-db-per-service"] = T + """
flowchart TB
  subgraph P["Pattern: Database-per-Service (no shared DB)"]
    direction LR
    CAT["Catalog"]:::svc --> CATDB[("catalog_db")]:::data
    ORD["Orders"]:::svc --> ORDDB[("orders_db")]:::data
    USR["Users"]:::svc --> USRDB[("users_db")]:::data
    INV["Inventory"]:::svc --> INVRD[("Redis")]:::data
  end
  NOTE["Each service OWNS its data. Others reach it only via the service API<br/>or via events - never by direct cross-service DB access.<br/>Enables independent scaling, schema evolution, and blast-radius isolation."]
""" + PALETTE

# ===========================================================================
# CHAPTER 2 — Bare metal to VMs
# ===========================================================================

DIAGRAMS["02-baremetal-to-vm"] = T + """
flowchart TB
  subgraph HW["Layer 1 - Physical (bare metal)"]
    S1["Server A<br/>2x CPU, 256GB RAM, NVMe"]:::plat
    S2["Server B<br/>2x CPU, 256GB RAM, NVMe"]:::plat
    S3["Server C<br/>2x CPU, 256GB RAM, NVMe"]:::plat
  end
  subgraph HYP["Layer 2 - Hypervisor (KVM / Proxmox)"]
    K1["KVM host A"]:::plat
    K2["KVM host B"]:::plat
    K3["KVM host C"]:::plat
  end
  subgraph VM["Layer 3 - Virtual Machines (cluster nodes)"]
    V1["cp + worker VMs"]:::svc
    V2["cp + worker VMs"]:::svc
    V3["cp + worker VMs"]:::svc
  end
  S1 --> K1 --> V1
  S2 --> K2 --> V2
  S3 --> K3 --> V3
""" + PALETTE

DIAGRAMS["02-vm-slicing"] = T + """
flowchart TB
  subgraph HOST["One physical host (256 GB RAM, 64 vCPU) sliced by KVM"]
    direction TB
    CP["control-plane VM<br/>4 vCPU / 8 GB"]:::edge
    W1["worker VM (general)<br/>8 vCPU / 32 GB"]:::svc
    W2["worker VM (general)<br/>8 vCPU / 32 GB"]:::svc
    W3["worker VM (data)<br/>12 vCPU / 64 GB + NVMe passthrough"]:::data
    RES["host reserve<br/>hypervisor + overhead"]:::plat
  end
  NOTE["Do NOT overcommit control-plane or etcd VMs.<br/>Pin data/storage VMs to hosts with local NVMe.<br/>Leave headroom for the hypervisor itself."]
""" + PALETTE

DIAGRAMS["02-host-vm-placement"] = T + """
flowchart LR
  subgraph A["Host A"]
    A1["cp-1"]:::edge
    A2["worker-gen-1"]:::svc
    A3["worker-data-1"]:::data
  end
  subgraph B["Host B"]
    B1["cp-2"]:::edge
    B2["worker-gen-2"]:::svc
    B3["worker-data-2"]:::data
  end
  subgraph C["Host C"]
    C1["cp-3"]:::edge
    C2["worker-gen-3"]:::svc
    C3["worker-data-3"]:::data
  end
  NOTE["Spread control-plane VMs across 3 hosts so one host failure<br/>never breaks etcd quorum. Same for stateful replicas (anti-affinity)."]
""" + PALETTE

# ===========================================================================
# CHAPTER 3 — Cluster topology
# ===========================================================================

DIAGRAMS["03-cluster-topology"] = T + """
flowchart TB
  LB["HAProxy / keepalived VIP<br/>control-plane API LB :6443"]:::edge
  subgraph CPP["Control plane (3 nodes - HA, etcd quorum)"]
    CP1["cp-1<br/>apiserver, etcd, scheduler, cm"]:::edge
    CP2["cp-2"]:::edge
    CP3["cp-3"]:::edge
  end
  subgraph GEN["General worker pool (4 nodes)"]
    G1["worker-gen-1"]:::svc
    G2["worker-gen-2"]:::svc
    G3["worker-gen-3"]:::svc
    G4["worker-gen-4"]:::svc
  end
  subgraph DAT["Data worker pool (3 nodes - local NVMe, tainted)"]
    D1["worker-data-1"]:::data
    D2["worker-data-2"]:::data
    D3["worker-data-3"]:::data
  end
  subgraph INF["Infra/edge pool (2 nodes)"]
    I1["worker-infra-1<br/>Gateway, monitoring"]:::plat
    I2["worker-infra-2"]:::plat
  end
  LB --> CP1 & CP2 & CP3
  CPP --> GEN & DAT & INF
""" + PALETTE

DIAGRAMS["03-control-plane-ha"] = T + """
flowchart TB
  KUBECTL["kubectl / kubelets"]:::user --> VIP["Virtual IP :6443<br/>keepalived + HAProxy"]:::edge
  VIP --> API1["apiserver cp-1"]:::edge
  VIP --> API2["apiserver cp-2"]:::edge
  VIP --> API3["apiserver cp-3"]:::edge
  API1 --- E1[("etcd-1")]:::data
  API2 --- E2[("etcd-2")]:::data
  API3 --- E3[("etcd-3")]:::data
  E1 <-.-> E2
  E2 <-.-> E3
  E1 <-.-> E3
  NOTE["etcd needs an ODD number for quorum (3 tolerates 1 failure,<br/>5 tolerates 2). Never run 2 or 4."]
""" + PALETTE

DIAGRAMS["03-node-pools"] = T + """
flowchart LR
  subgraph POOLS["Node pools = labels + taints steer scheduling"]
    direction TB
    GEN["pool=general<br/>(no taint)<br/>stateless services"]:::svc
    DATA["pool=data<br/>taint: data=true:NoSchedule<br/>Postgres, Kafka, Ceph OSD"]:::data
    INFRA["pool=infra<br/>taint: infra=true:NoSchedule<br/>Gateway, Prometheus, Grafana"]:::plat
  end
  NOTE["Workloads request a pool via nodeSelector + tolerations.<br/>Taints keep general apps OFF data/infra nodes."]
""" + PALETTE

# ===========================================================================
# CHAPTER 4 — Network design
# ===========================================================================

DIAGRAMS["04-network-layout"] = T + """
flowchart TB
  INET["Internet"]:::user --> FW["Firewall / Edge router"]:::edge
  FW --> VMGMT["VLAN 10 - Management<br/>10.10.0.0/24 (SSH, iLO, kube API)"]:::plat
  FW --> VAPP["VLAN 20 - App / MetalLB pool<br/>10.20.0.0/24 (LoadBalancer IPs)"]:::edge
  subgraph CLUSTER["In-cluster software networks (overlay)"]
    POD["Pod CIDR<br/>10.244.0.0/16 (Cilium)"]:::svc
    SVC["Service CIDR<br/>10.96.0.0/12 (ClusterIP)"]:::svc
  end
  VAPP --> CLUSTER
""" + PALETTE

DIAGRAMS["04-north-south"] = T + """
flowchart LR
  U["User"]:::user --> DNS["DNS -> MetalLB VIP"]:::edge
  DNS --> LB["MetalLB (L2/BGP)<br/>assigns external IP"]:::edge
  LB --> ING["Cilium Gateway (Gateway API)"]:::edge
  ING --> SVC["Service (ClusterIP)"]:::svc
  SVC --> POD["Pod (endpoint)"]:::svc
  NOTE["North-South = traffic entering the cluster from outside.<br/>MetalLB gives bare-metal the 'LoadBalancer' service type<br/>that cloud providers give for free."]
""" + PALETTE

DIAGRAMS["04-east-west"] = T + """
flowchart LR
  P1["Orders pod<br/>10.244.3.11"]:::svc -->|"ClusterIP DNS:<br/>inventory.svc"| P2["Inventory pod<br/>10.244.5.22"]:::svc
  P2 -->|"eBPF routing"| P3["Redis pod<br/>10.244.7.9"]:::data
  NOTE["East-West = pod-to-pod traffic inside the cluster.<br/>Cilium eBPF routes packets in-kernel (no iptables hairpin),<br/>and enforces NetworkPolicy at the same layer."]
""" + PALETTE

DIAGRAMS["04-cilium-datapath"] = T + """
flowchart TB
  subgraph NODE["Worker node (Linux kernel)"]
    direction TB
    POD["Pod netns<br/>eth0 (veth)"]:::svc
    EBPF["eBPF programs<br/>at tc / socket hooks"]:::plat
    ROUTE["Routing / encapsulation<br/>(VXLAN or native)"]:::plat
  end
  POD --> EBPF --> ROUTE --> NIC["Physical NIC"]:::edge
  HUBBLE["Hubble<br/>flow visibility"]:::plat -.-> EBPF
  NOTE["Cilium loads eBPF into the kernel to do routing, load-balancing,<br/>and NetworkPolicy without kube-proxy/iptables. Hubble taps the<br/>same hooks for L3-L7 observability."]
""" + PALETTE

# ===========================================================================
# CHAPTER 5 — kubeadm HA install
# ===========================================================================

DIAGRAMS["05-kubeadm-flow"] = T + """
flowchart TB
  A["1. Prep ALL nodes<br/>containerd, kubeadm, kubelet, kubectl<br/>swap off, sysctls"]:::plat
  B["2. kubeadm init on cp-1<br/>--control-plane-endpoint VIP<br/>--upload-certs"]:::edge
  C["3. Install CNI (Cilium)<br/>nodes go Ready"]:::svc
  D["4. Join cp-2, cp-3<br/>kubeadm join ... --control-plane"]:::edge
  E["5. Join all workers<br/>kubeadm join ..."]:::svc
  F["6. Label + taint node pools"]:::plat
  A --> B --> C --> D --> E --> F
""" + PALETTE

DIAGRAMS["05-bootstrap-sequence"] = T + """
sequenceDiagram
  autonumber
  participant Admin
  participant CP1 as cp-1
  participant ETCD as etcd
  participant API as kube-apiserver
  Admin->>CP1: kubeadm init (control-plane-endpoint VIP)
  CP1->>CP1: preflight checks
  CP1->>CP1: generate CA + all certs
  CP1->>ETCD: start local etcd (static pod)
  CP1->>API: start apiserver, scheduler, controller-manager
  API-->>Admin: admin.conf (kubeconfig)
  Admin->>API: apply Cilium CNI
  Note over Admin,API: nodes transition NotReady to Ready once CNI is up
  Admin->>CP1: print join commands (worker + control-plane)
""" 

DIAGRAMS["05-component-layout"] = T + """
flowchart TB
  subgraph CP["Control-plane node (static pods)"]
    API["kube-apiserver"]:::edge
    ETCD[("etcd")]:::data
    SCH["kube-scheduler"]:::edge
    CM["kube-controller-manager"]:::edge
    KL1["kubelet"]:::plat
  end
  subgraph W["Worker node"]
    KL2["kubelet"]:::plat
    CIL["cilium-agent (DaemonSet)"]:::svc
    PODS["application pods"]:::svc
    CR["containerd"]:::plat
  end
  API --- ETCD
  KL2 --> CR --> PODS
""" + PALETTE

# ===========================================================================
# CHAPTER 6 — Cilium CNI + Hubble
# ===========================================================================

DIAGRAMS["06-cilium-arch"] = T + """
flowchart TB
  OP["cilium-operator<br/>(Deployment) - IPAM, GC"]:::plat
  subgraph NODES["Every node runs a cilium-agent (DaemonSet)"]
    A1["cilium-agent node-1<br/>programs eBPF"]:::svc
    A2["cilium-agent node-2"]:::svc
    A3["cilium-agent node-3"]:::svc
  end
  API["kube-apiserver"]:::edge
  OP --> API
  A1 --> API
  A2 --> API
  A3 --> API
  A1 -. "eBPF maps" .-> K1["kernel node-1"]:::data
  NOTE["Agent = per-node brain that compiles policy + service<br/>definitions into eBPF. Operator = one-per-cluster housekeeping."]
""" + PALETTE

DIAGRAMS["06-hubble"] = T + """
flowchart LR
  EBPF["eBPF datapath<br/>(per node)"]:::plat --> RELAY["hubble-relay<br/>aggregates flows"]:::svc
  RELAY --> UI["Hubble UI<br/>live service map"]:::edge
  RELAY --> CLI["hubble CLI<br/>hubble observe"]:::edge
  NOTE["Hubble turns the eBPF flow data into L3/L4/L7 visibility:<br/>who talked to whom, verdict (allowed/denied), latency, HTTP path."]
""" + PALETTE

# ===========================================================================
# CHAPTER 7 — MetalLB + Cilium Gateway API
# ===========================================================================

DIAGRAMS["07-metallb-arch"] = T + """
flowchart TB
  CTRL["metallb controller<br/>(Deployment)<br/>allocates IPs from pool"]:::plat
  subgraph SPK["metallb speakers (DaemonSet)"]
    S1["speaker node-1"]:::svc
    S2["speaker node-2"]:::svc
  end
  POOL["IPAddressPool<br/>10.20.0.100-200"]:::edge
  CTRL --> POOL
  S1 -. "L2: ARP/NDP or BGP" .-> ROUTER["Data-center router"]:::edge
  NOTE["Controller assigns an external IP to a LoadBalancer Service.<br/>Speakers advertise that IP so external traffic reaches a node."]
""" + PALETTE

DIAGRAMS["07-ingress-flow"] = T + """
flowchart TB
  U["User https://tickethub.com"]:::user --> LBIP["MetalLB IP 10.20.0.100<br/>(LoadBalancer svc)"]:::edge
  LBIP --> INGC["Cilium Gateway (Gateway API)"]:::edge
  INGC -->|"HTTPRoute rules"| R1["/ -> frontend-svc"]:::svc
  INGC --> R2["/api -> gateway-svc"]:::svc
  INGC --> R3["/search -> search-svc"]:::svc
  R1 --> FE["frontend pods"]:::svc
  R2 --> GW["gateway pods"]:::svc
  NOTE["A Gateway declares listeners + TLS; HTTPRoutes declare routing.<br/>Cilium programs the data plane. MetalLB gives the Gateway its public IP."]
""" + PALETTE

DIAGRAMS["07-cert-manager"] = T + """
flowchart LR
  ING["Gateway<br/>cluster-issuer: letsencrypt<br/>tls secretName: tickethub-tls"]:::svc
  CM["cert-manager<br/>(operator)"]:::edge
  LE["Let's Encrypt<br/>(ACME CA)"]:::plat
  SEC["Secret tickethub-tls<br/>(cert + key)"]:::data
  NGINX["Cilium Gateway<br/>serves HTTPS"]:::edge
  ING -->|"1. annotation seen"| CM
  CM -->|"2. request cert + HTTP-01 challenge"| LE
  LE -->|"3. fetch /.well-known/... token"| NGINX
  LE -->|"4. signed cert"| CM
  CM -->|"5. write"| SEC
  SEC -->|"6. mount + serve"| NGINX
  NOTE["cert-manager sees the annotation, proves domain ownership via the<br/>HTTP-01 challenge (served through a temporary HTTPRoute on the Gateway),<br/>gets a signed cert from Let's Encrypt, stores it in the Secret, auto-renews."]
""" + PALETTE

# ===========================================================================
# CHAPTER 7A — Certificate & PKI management
# ===========================================================================

DIAGRAMS["07b-pki-hierarchy"] = T + """
flowchart TB
  subgraph ROOTS["Three CAs created by kubeadm init"]
    KCA["kubernetes-ca"]:::edge
    ECA["etcd-ca"]:::data
    FCA["front-proxy-ca"]:::plat
  end
  KCA --> APISRV["apiserver<br/>(serving)"]:::svc
  KCA --> AKC["apiserver-kubelet-client"]:::svc
  KCA --> KUBELET["kubelet client/serving<br/>(per node)"]:::svc
  KCA --> ADMIN["admin.conf<br/>(break-glass)"]:::svc
  ECA --> ESRV["etcd server"]:::svc
  ECA --> EPEER["etcd peer"]:::svc
  ECA --> AEC["apiserver-etcd-client"]:::svc
  FCA --> FPC["front-proxy-client"]:::svc
  SA["SA signing keypair<br/>(sa.key / sa.pub)"]:::plat
  SA -.->|"signs JWTs, not TLS"| TOK["ServiceAccount tokens"]:::data
  NOTE["Everything lives under /etc/kubernetes/pki. Three independent CAs plus a<br/>token-signing keypair. Each arrow in the control plane is already mTLS."]
""" + PALETTE

DIAGRAMS["07b-ha-certs"] = T + """
flowchart TB
  VIP["HAProxy VIP 10.10.0.10<br/>(control-plane-endpoint)"]:::edge
  subgraph CP["3 control-plane nodes - each has its OWN leaf certs, shared CA"]
    C1["cp-1 apiserver.crt<br/>SANs: VIP + cp-1/2/3 + svc IP"]:::svc
    C2["cp-2 apiserver.crt<br/>SANs: VIP + cp-1/2/3 + svc IP"]:::svc
    C3["cp-3 apiserver.crt<br/>SANs: VIP + cp-1/2/3 + svc IP"]:::svc
  end
  VIP --> C1
  VIP --> C2
  VIP --> C3
  subgraph ETCD["etcd mesh - peer.crt does client AND server auth"]
    E1["etcd-1 peer/server"]:::data
    E2["etcd-2 peer/server"]:::data
    E3["etcd-3 peer/server"]:::data
  end
  E1 <--> E2
  E2 <--> E3
  E1 <--> E3
  NOTE["HA does not share leaf certs: each node generates its own, signed by the<br/>shared CA distributed at join (--upload-certs). Every apiserver cert must<br/>list the VIP as a SAN, or calls through the load balancer fail TLS."]
""" + PALETTE

DIAGRAMS["07b-internal-ca"] = T + """
flowchart LR
  SS["selfsigned-root<br/>ClusterIssuer"]:::plat --> ROOT["tickethub-root-ca<br/>Certificate (isCA)<br/>Secret: root key+cert"]:::edge
  ROOT --> CAI["tickethub-internal<br/>CA ClusterIssuer"]:::edge
  CAI --> OC["orders-tls<br/>Secret (all replicas)"]:::svc
  CAI --> PC["payments-tls<br/>Secret"]:::svc
  ROOT --> TM["trust-manager Bundle"]:::plat
  TM -->|"CA bundle ConfigMap<br/>to every namespace"| NS["ns: tickethub / data / ..."]:::data
  NOTE["A self-signed issuer signs the root CA; the root becomes a CA issuer that<br/>signs per-service certs. trust-manager publishes the CA bundle to every<br/>namespace so peers trust the certs. Same automation as public TLS, private root."]
""" + PALETTE

# ===========================================================================
# CHAPTER 8 — Rook-Ceph storage
# ===========================================================================

DIAGRAMS["08-rook-ceph-arch"] = T + """
flowchart TB
  OP["Rook operator<br/>(watches CephCluster CRD)"]:::plat
  subgraph DATANODES["Data node pool (local NVMe)"]
    MON["ceph-mon x3<br/>cluster map + quorum"]:::edge
    MGR["ceph-mgr<br/>metrics, dashboard"]:::edge
    OSD1["OSD (disk 1)"]:::data
    OSD2["OSD (disk 2)"]:::data
    OSD3["OSD (disk 3)"]:::data
  end
  OP --> MON
  OP --> MGR
  OP --> OSD1 & OSD2 & OSD3
  NOTE["Rook = Kubernetes operator that runs Ceph. OSDs own the raw disks,<br/>mons keep quorum on the cluster map, mgr exposes metrics/dashboard."]
""" + PALETTE

DIAGRAMS["08-storage-provisioning"] = T + """
sequenceDiagram
  autonumber
  participant App as Pod / StatefulSet
  participant PVC as PersistentVolumeClaim
  participant SC as StorageClass (rook-ceph-block)
  participant CSI as Ceph CSI driver
  participant Ceph
  App->>PVC: mount claim (5Gi, RWO)
  PVC->>SC: which provisioner?
  SC->>CSI: provision 5Gi RBD image
  CSI->>Ceph: create RBD volume
  Ceph-->>CSI: volume ready
  CSI-->>PVC: bind PersistentVolume
  PVC-->>App: volume mounted at /data
""" 

DIAGRAMS["08-storage-types"] = T + """
flowchart LR
  subgraph BLOCK["Block (RBD) - RWO"]
    B1["Postgres, single-writer DBs"]:::data
  end
  subgraph FILE["File (CephFS) - RWX"]
    F1["shared uploads, multi-pod read/write"]:::data
  end
  subgraph OBJ["Object (RGW / S3) - HTTP"]
    O1["Search index, backups, tickets PDF"]:::data
  end
  NOTE["One Ceph cluster serves all three storage APIs.<br/>Pick per workload: RWO block for DBs, RWX file for sharing,<br/>S3 object for blobs and backups."]
""" + PALETTE

# ===========================================================================
# CHAPTER 9 — Namespaces, resource model, bootstrap order
# ===========================================================================

DIAGRAMS["09-namespaces"] = T + """
flowchart TB
  subgraph CLUSTER["Cluster namespaces"]
    NS1["tickethub<br/>(9 app services)"]:::svc
    NS2["data<br/>(Postgres, Redis, Kafka)"]:::data
    NS3["platform<br/>(ingress, metallb, cert-manager)"]:::edge
    NS4["rook-ceph<br/>(storage)"]:::data
    NS5["monitoring<br/>(Prometheus, Grafana, Loki)"]:::plat
    NS6["security<br/>(Falco, Kyverno)"]:::plat
    NS7["argocd<br/>(GitOps)"]:::plat
  end
  NOTE["Namespaces = the unit of isolation for RBAC, ResourceQuota,<br/>NetworkPolicy and PSA. Group by ownership and blast radius."]
""" + PALETTE

DIAGRAMS["09-bootstrap-order"] = T + """
flowchart LR
  S1["1. Cluster (kubeadm)"]:::edge --> S2["2. CNI (Cilium)"]:::svc
  S2 --> S3["3. Storage (Rook-Ceph)<br/>+ StorageClasses"]:::data
  S3 --> S4["4. LB + Gateway<br/>(MetalLB, Cilium GW API)"]:::edge
  S4 --> S5["5. Platform<br/>(cert-manager, ESO)"]:::plat
  S5 --> S6["6. Security + policy<br/>(PSA, Kyverno, Falco)"]:::plat
  S6 --> S7["7. Observability"]:::plat
  S7 --> S8["8. Stateful data<br/>(Postgres, Kafka, Redis)"]:::data
  S8 --> S9["9. App services"]:::svc
  NOTE["Dependencies flow left to right. Nothing schedules without a CNI.<br/>Nothing persists without storage. Apps come last."]
""" + PALETTE

DIAGRAMS["09-resource-model"] = T + """
flowchart TB
  C["Cluster"]:::edge --> N["Namespace<br/>ResourceQuota + LimitRange"]:::plat
  N --> D["Workload<br/>Deployment / StatefulSet"]:::svc
  D --> P["Pod<br/>(scheduling unit)"]:::svc
  P --> CT["Container<br/>requests + limits"]:::data
  NOTE["Requests/limits are set per CONTAINER, summed per POD,<br/>capped per NAMESPACE by ResourceQuota. The scheduler places<br/>pods based on requests vs node allocatable."]
""" + PALETTE

# ===========================================================================
# CHAPTER 10 — Containerizing the services (Dockerfiles)
# ===========================================================================

DIAGRAMS["10-multistage-build"] = T + """
flowchart LR
  subgraph B1["Stage 1: builder"]
    SRC["source code<br/>+ build deps (SDK)"]:::plat --> COMP["compile / bundle<br/>go build, npm ci"]:::plat
    COMP --> ART["artifact<br/>(binary / dist)"]:::edge
  end
  subgraph B2["Stage 2: runtime (distroless)"]
    BASE["minimal base<br/>no shell, no pkg mgr"]:::svc
    ART -->|"COPY --from=builder"| BASE
    BASE --> IMG["final image<br/>tiny + non-root"]:::svc
  end
  NOTE["Multi-stage keeps the heavy SDK out of the shipped image.<br/>Only the compiled artifact lands in a minimal, non-root runtime."]
""" + PALETTE

DIAGRAMS["10-image-anatomy"] = T + """
flowchart TB
  subgraph IMG["Container image = stacked read-only layers"]
    L1["base layer (distroless)"]:::svc
    L2["deps layer"]:::svc
    L3["app artifact layer"]:::edge
    L4["config / metadata (ENTRYPOINT, USER)"]:::plat
  end
  L1 --> L2 --> L3 --> L4
  RW["+ writable container layer (ephemeral, at runtime)"]:::data
  L4 --> RW
  NOTE["Layers are cached and shared. Order Dockerfile steps<br/>least-to-most changing so deps cache survives code edits."]
""" + PALETTE

DIAGRAMS["10-build-supply-chain"] = T + """
sequenceDiagram
  autonumber
  participant Dev
  participant CI as CI pipeline
  participant Scan as Trivy (scan)
  participant Sign as cosign (sign)
  participant Reg as Registry
  participant K8s as Cluster
  Dev->>CI: git push
  CI->>CI: docker build (multi-stage)
  CI->>Scan: scan image for CVEs
  Scan-->>CI: pass / fail (block on HIGH)
  CI->>Sign: sign image digest
  CI->>Reg: push image + signature
  K8s->>Reg: pull by digest
  Note over K8s: admission verifies signature before running (Ch 24)
""" 

DIAGRAMS["10-private-registry"] = T + """
flowchart LR
  CI["CI pipeline"]:::edge -->|"docker push (auth)"| REG["registry.internal<br/>private OCI registry<br/>(Harbor / Distribution)"]:::data
  subgraph NODE["worker node"]
    KUBELET["kubelet"]:::plat
    POD["orders pod"]:::svc
  end
  SEC["imagePullSecret<br/>(dockerconfigjson)"]:::edge
  SA["namespace default<br/>ServiceAccount"]:::plat
  SEC --> SA
  SA -->|"grants pull creds"| KUBELET
  KUBELET -->|"pull image (authenticated)"| REG
  KUBELET --> POD
  NOTE["CI pushes images to the private registry. On scheduling, the kubelet<br/>pulls the image using the imagePullSecret attached to the namespace<br/>ServiceAccount. No secret = ImagePullBackOff."]
""" + PALETTE

# ===========================================================================
# CHAPTER 11 — Workload controllers
# ===========================================================================

DIAGRAMS["11-controller-types"] = T + """
flowchart TB
  subgraph STATELESS["Stateless"]
    DEP["Deployment<br/>rolling updates, N replicas<br/>frontend, gateway, catalog..."]:::svc
  end
  subgraph STATEFUL["Stateful"]
    STS["StatefulSet<br/>stable identity + storage<br/>Postgres, Kafka, Redis"]:::data
  end
  subgraph NODEWIDE["One-per-node"]
    DS["DaemonSet<br/>node agents<br/>cilium, node-exporter, falco"]:::plat
  end
  subgraph BATCH["Run-to-completion"]
    JOB["Job / CronJob<br/>migrations, nightly reports"]:::edge
  end
  NOTE["Pick the controller by workload shape: interchangeable replicas -> Deployment,<br/>identity + disk -> StatefulSet, per-node agent -> DaemonSet, batch -> Job."]
""" + PALETTE

DIAGRAMS["11-deployment-hierarchy"] = T + """
flowchart TB
  DEP["Deployment (catalog)<br/>desired: 3 replicas, image v2"]:::edge
  DEP --> RS2["ReplicaSet v2<br/>(current)"]:::svc
  DEP -.-> RS1["ReplicaSet v1<br/>(old, scaled to 0 - kept for rollback)"]:::plat
  RS2 --> P1["pod"]:::svc
  RS2 --> P2["pod"]:::svc
  RS2 --> P3["pod"]:::svc
  NOTE["Deployment manages ReplicaSets; a rollout creates a new ReplicaSet<br/>and shifts pods over. Old ReplicaSets stay at 0 for instant rollback."]
""" + PALETTE

DIAGRAMS["11-statefulset"] = T + """
flowchart TB
  STS["StatefulSet: postgres"]:::edge
  STS --> P0["postgres-0<br/>(primary)"]:::data
  STS --> P1["postgres-1<br/>(replica)"]:::data
  STS --> P2["postgres-2<br/>(replica)"]:::data
  P0 --> V0[("pvc: data-postgres-0")]:::data
  P1 --> V1[("pvc: data-postgres-1")]:::data
  P2 --> V2[("pvc: data-postgres-2")]:::data
  HS["Headless Service<br/>postgres (clusterIP: None)"]:::svc -.->|"stable DNS<br/>postgres-0.postgres"| P0
  NOTE["Each pod has a stable name, stable DNS, and its OWN PVC that<br/>follows it across reschedules. Created/scaled in order 0,1,2."]
""" + PALETTE

# ===========================================================================
# CHAPTER 12 — Services & traffic
# ===========================================================================

DIAGRAMS["12-service-types"] = T + """
flowchart TB
  subgraph CIP["ClusterIP (default)"]
    C1["internal only<br/>catalog-svc -> catalog pods"]:::svc
  end
  subgraph HL["Headless (clusterIP: None)"]
    H1["direct pod DNS<br/>StatefulSets: postgres-0.postgres"]:::data
  end
  subgraph NP["NodePort"]
    N1["node IP : 30000-32767<br/>rarely used directly"]:::edge
  end
  subgraph LB["LoadBalancer (via MetalLB)"]
    L1["external IP from pool<br/>ingress controller"]:::edge
  end
  NOTE["ClusterIP for east-west, Headless for stable per-pod DNS,<br/>LoadBalancer (MetalLB) for the ingress entrypoint."]
""" + PALETTE

DIAGRAMS["12-service-endpoints"] = T + """
flowchart LR
  DNS["orders-svc<br/>(ClusterIP 10.96.x.x)"]:::svc --> EP["EndpointSlice<br/>(healthy pod IPs)"]:::plat
  EP --> P1["orders pod A"]:::svc
  EP --> P2["orders pod B"]:::svc
  EP --> P3["orders pod C"]:::svc
  SEL["selector: app=orders<br/>+ readiness probe"]:::edge -.-> EP
  NOTE["A Service is a stable name/VIP. Its selector + readiness gates<br/>which pod IPs land in the EndpointSlice. Cilium eBPF load-balances<br/>to those IPs. Only Ready pods receive traffic."]
""" + PALETTE

DIAGRAMS["12-request-path"] = T + """
flowchart LR
  U["User"]:::user --> ING["Cilium Gateway (Gateway API)"]:::edge
  ING -->|"/api"| GW["gateway-svc<br/>ClusterIP"]:::svc
  GW --> GWP["gateway pod"]:::svc
  GWP -->|"orders-svc"| OS["orders-svc"]:::svc
  OS --> OP["orders pod"]:::svc
  OP -->|"postgres.data"| DB[("postgres-0")]:::data
  NOTE["North-south enters via the Gateway. East-west hops go service-to-service<br/>by ClusterIP DNS name. Every hop is a Service, never a raw pod IP."]
""" + PALETTE

# ===========================================================================
# CHAPTER 13 — Configuration & secrets
# ===========================================================================

DIAGRAMS["13-config-injection"] = T + """
flowchart TB
  CM["ConfigMap<br/>(non-secret settings)"]:::plat
  SEC["Secret<br/>(base64, encrypted at rest)"]:::data
  POD["Pod: orders"]:::svc
  CM -->|"envFrom / env"| POD
  CM -->|"mounted file<br/>/etc/config/app.yaml"| POD
  SEC -->|"env: DB_PASSWORD"| POD
  SEC -->|"mounted file<br/>/etc/secrets/db"| POD
  NOTE["Same two injection styles for both: environment variables or<br/>mounted files. Keep config OUT of the image so one image runs<br/>in dev/stage/prod unchanged."]
""" + PALETTE

DIAGRAMS["13-external-secrets"] = T + """
flowchart LR
  VAULT["External store<br/>(Vault / AWS SM)"]:::data --> ESO["External Secrets<br/>Operator"]:::plat
  ESO -->|"syncs"| K8SEC["Kubernetes Secret<br/>(in namespace)"]:::data
  K8SEC --> POD["Pod consumes<br/>env / volume"]:::svc
  ES["ExternalSecret CR<br/>(what to fetch)"]:::edge -.-> ESO
  NOTE["Secrets live in a real vault, not in Git. ESO reconciles them into<br/>native k8s Secrets so pods consume them normally. Rotations propagate."]
""" + PALETTE

# ===========================================================================
# CHAPTER 14 — Stateful storage (volumeClaimTemplates)
# ===========================================================================

DIAGRAMS["14-volumeclaimtemplates"] = T + """
flowchart TB
  STS["StatefulSet: kafka<br/>volumeClaimTemplates: data 50Gi"]:::edge
  STS --> P0["kafka-0"]:::svc
  STS --> P1["kafka-1"]:::svc
  STS --> P2["kafka-2"]:::svc
  P0 --> C0["pvc data-kafka-0"]:::plat --> V0[("PV: Ceph RBD")]:::data
  P1 --> C1["pvc data-kafka-1"]:::plat --> V1[("PV: Ceph RBD")]:::data
  P2 --> C2["pvc data-kafka-2"]:::plat --> V2[("PV: Ceph RBD")]:::data
  NOTE["The template mints one PVC per replica automatically. Deleting the<br/>StatefulSet does NOT delete the PVCs - data survives on purpose."]
""" + PALETTE

DIAGRAMS["14-pvc-lifecycle"] = T + """
sequenceDiagram
  autonumber
  participant STS as StatefulSet
  participant PVC as PVC (data-kafka-0)
  participant SC as StorageClass
  participant Sched as Scheduler
  participant Node
  STS->>PVC: create from volumeClaimTemplate
  PVC->>SC: WaitForFirstConsumer
  STS->>Sched: schedule kafka-0
  Sched->>Node: pod assigned
  Node->>SC: now provision PV near this node
  SC-->>PVC: PV bound
  Node->>Node: mount volume, start kafka-0
  Note over PVC,Node: on reschedule, same PVC re-attaches - identity + data preserved
""" 

# ===========================================================================
# CHAPTER 15 — Resource management, QoS, quotas
# ===========================================================================

DIAGRAMS["15-requests-limits"] = T + """
flowchart TB
  subgraph POD["Container resource spec"]
    REQ["requests<br/>cpu 100m / mem 128Mi<br/>= GUARANTEED, used for scheduling"]:::svc
    LIM["limits<br/>cpu 500m / mem 512Mi<br/>= CEILING, enforced at runtime"]:::edge
  end
  REQ -->|"scheduler compares to<br/>node allocatable"| SCHED["Scheduler places pod"]:::plat
  LIM -->|"CPU throttled / Mem OOMKilled<br/>if exceeded"| RUN["kubelet + cgroups"]:::data
  NOTE["Requests = what you reserve (scheduling). Limits = the hard cap<br/>(runtime). CPU over limit is throttled; memory over limit is OOMKilled."]
""" + PALETTE

DIAGRAMS["15-qos-classes"] = T + """
flowchart TB
  G["Guaranteed<br/>requests == limits (both set)<br/>last to be evicted"]:::svc
  B["Burstable<br/>requests < limits<br/>evicted after BestEffort"]:::edge
  BE["BestEffort<br/>no requests/limits<br/>FIRST evicted under pressure"]:::data
  NODE["Node under memory pressure<br/>eviction order ->"]:::plat
  NODE --> BE --> B --> G
  NOTE["QoS class is derived from requests/limits. Give critical services<br/>(payments, DB) Guaranteed QoS so they survive node pressure."]
""" + PALETTE

DIAGRAMS["15-quota-limitrange"] = T + """
flowchart TB
  NS["Namespace: tickethub"]:::plat
  NS --> RQ["ResourceQuota<br/>caps TOTAL: cpu 40, mem 80Gi, pods 200"]:::edge
  NS --> LR["LimitRange<br/>per-container DEFAULTS + max/min"]:::edge
  LR --> P1["pod without requests<br/>-> gets defaults injected"]:::svc
  RQ --> BLOCK["new pod that would exceed quota<br/>-> REJECTED at admission"]:::data
  NOTE["ResourceQuota bounds the whole namespace budget. LimitRange sets<br/>per-container defaults so no pod is unbounded. Both admission-time."]
""" + PALETTE

# ===========================================================================
# CHAPTER 16 — Autoscaling
# ===========================================================================

DIAGRAMS["16-autoscaler-layers"] = T + """
flowchart TB
  subgraph POD["Pod-level"]
    HPA["HPA<br/>more/fewer REPLICAS<br/>(horizontal)"]:::svc
    VPA["VPA<br/>bigger/smaller requests<br/>(vertical)"]:::edge
    KEDA["KEDA<br/>event-driven scale<br/>(Kafka lag, queue depth)"]:::evt
  end
  subgraph NODE["Node-level"]
    CA["Cluster Autoscaler<br/>add/remove NODES/VMs"]:::plat
  end
  HPA -->|"needs capacity"| CA
  KEDA --> HPA
  NOTE["HPA scales replicas out, VPA right-sizes each pod, KEDA reacts to<br/>event sources, Cluster Autoscaler grows the node pool when pods pend."]
""" + PALETTE

DIAGRAMS["16-hpa-loop"] = T + """
sequenceDiagram
  autonumber
  participant MS as Metrics Server
  participant HPA as HorizontalPodAutoscaler
  participant DEP as Deployment
  participant Pods
  loop every 15s
    HPA->>MS: current CPU / custom metric?
    MS-->>HPA: pods avg 82% CPU (target 70%)
    HPA->>HPA: desired = ceil(current * (82/70))
    HPA->>DEP: scale replicas 3 -> 4
    DEP->>Pods: create 1 more pod
  end
  Note over HPA,Pods: scale-up fast, scale-down slow (stabilization window)
""" 

DIAGRAMS["16-custom-metrics"] = T + """
flowchart LR
  APP["orders pods<br/>/metrics: http_requests_total"]:::svc
  PROM["Prometheus<br/>scrapes + stores"]:::edge
  ADAPTER["prometheus-adapter<br/>serves custom.metrics.k8s.io"]:::plat
  HPA["HorizontalPodAutoscaler<br/>target: 50 rps/pod"]:::edge
  DEP["orders Deployment"]:::svc
  APP -->|"scrape"| PROM
  PROM -->|"PromQL rate()"| ADAPTER
  HPA -->|"query custom metric"| ADAPTER
  HPA -->|"scale"| DEP
  DEP --> APP
  NOTE["HPA cannot read Prometheus directly. prometheus-adapter translates a<br/>PromQL rate() into the custom.metrics.k8s.io API that HPA understands.<br/>Break any link and the HPA sees the metric as unknown."]
""" + PALETTE

DIAGRAMS["16-cluster-autoscaler"] = T + """
flowchart LR
  PEND["Pod Pending<br/>(no node has room)"]:::data --> CA["Cluster Autoscaler"]:::plat
  CA -->|"provision"| VM["new worker VM<br/>joins cluster"]:::svc
  VM --> SCHED["pod schedules"]:::svc
  CA -.->|"node underused >10min<br/>drain + remove"| SCALEDOWN["reclaim VM"]:::edge
  NOTE["When pods can't fit, CA adds nodes. When nodes sit underused, CA<br/>drains and removes them. Pairs with HPA: HPA needs pods, CA needs room."]
""" + PALETTE

# ===========================================================================
# CHAPTER 17 — Scheduling & placement
# ===========================================================================

DIAGRAMS["17-scheduling-cycle"] = T + """
flowchart LR
  Q["Pending pod"]:::data --> F["FILTER (predicates)<br/>taints, resources, affinity,<br/>nodeSelector -> feasible nodes"]:::edge
  F --> S["SCORE (priorities)<br/>spread, least-loaded,<br/>affinity weight -> rank"]:::svc
  S --> B["BIND<br/>pod -> best node"]:::plat
  NOTE["The scheduler first FILTERS out nodes that can't run the pod,<br/>then SCORES the survivors and BINDS to the highest scorer."]
""" + PALETTE

DIAGRAMS["17-affinity-taints"] = T + """
flowchart TB
  subgraph DATA["Data nodes (tainted: data=NoSchedule)"]
    DN["only pods that TOLERATE land here"]:::data
  end
  subgraph GEN["General nodes (label pool=general)"]
    GN["app pods via nodeAffinity pool=general"]:::svc
  end
  PG["postgres pod<br/>toleration: data + affinity pool=data"]:::data --> DN
  APP["catalog pod<br/>affinity pool=general"]:::svc --> GN
  ANTI["podAntiAffinity: spread replicas<br/>across different nodes"]:::edge -.-> GN
  NOTE["Taints REPEL pods (need matching toleration). Affinity ATTRACTS pods<br/>to labels. Anti-affinity keeps replicas off the same node."]
""" + PALETTE

DIAGRAMS["17-topology-spread"] = T + """
flowchart TB
  subgraph R1["Rack A"]
    A1["catalog pod"]:::svc
  end
  subgraph R2["Rack B"]
    B1["catalog pod"]:::svc
  end
  subgraph R3["Rack C"]
    C1["catalog pod"]:::svc
  end
  TSC["topologySpreadConstraints<br/>maxSkew 1 over zone"]:::edge --> R1 & R2 & R3
  PDB["PodDisruptionBudget<br/>minAvailable 2"]:::plat
  NOTE["Topology spread balances replicas evenly across zones/racks.<br/>PDB guarantees a minimum stay up during drains/upgrades."]
""" + PALETTE

DIAGRAMS["17-priorityclass"] = T + """
flowchart TB
  HIGH["PriorityClass: payments-critical (100000)"]:::edge --> PP["payments pod"]:::svc
  LOW["PriorityClass: batch-low (100)"]:::plat --> BP["report job pod"]:::data
  NODE["Node full - high-pri pod Pending"]:::data
  PP -->|"preempts"| EVICT["evict low-pri batch pod"]:::edge
  EVICT --> BP
  NOTE["Higher PriorityClass wins scheduling and can PREEMPT lower-priority<br/>pods when the cluster is full. Reserve top tiers for revenue-critical work."]
""" + PALETTE

# ===========================================================================
# CHAPTER 18 — Health & lifecycle
# ===========================================================================

DIAGRAMS["18-probes"] = T + """
flowchart TB
  START["Container starts"]:::plat --> SP["startupProbe<br/>is it booted yet?<br/>(protects slow starters)"]:::edge
  SP -->|"pass"| RP["readinessProbe<br/>ready for traffic?<br/>gates EndpointSlice"]:::svc
  SP -->|"fail x N"| KILL1["restart container"]:::data
  RP -->|"pass"| SERVE["receives traffic"]:::svc
  RP -->|"fail"| NOEP["removed from Service<br/>(NOT restarted)"]:::edge
  LP["livenessProbe<br/>still alive?"]:::plat -->|"fail x N"| KILL2["restart container"]:::data
  SERVE --> LP
  NOTE["startup gates the others, readiness gates TRAFFIC (no restart),<br/>liveness gates RESTART. Three probes, three different jobs."]
""" + PALETTE

DIAGRAMS["18-rollout"] = T + """
flowchart LR
  V1["3x v1 (serving)"]:::svc --> STEP1["+1 v2 (surge)<br/>wait Ready"]:::edge
  STEP1 --> STEP2["-1 v1 once v2 Ready"]:::edge
  STEP2 --> REPEAT["repeat until 3x v2"]:::edge
  REPEAT --> DONE["3x v2 (serving)"]:::svc
  BAD["v2 fails readiness"]:::data -.->|"rollout halts<br/>old pods stay up"| STEP1
  NOTE["RollingUpdate maxUnavailable 0 / maxSurge 1: add a Ready v2 before<br/>removing a v1. Failed readiness halts the rollout - no outage."]
""" + PALETTE

DIAGRAMS["18-graceful-shutdown"] = T + """
sequenceDiagram
  autonumber
  participant K as kubelet
  participant EP as EndpointSlice
  participant Pod
  participant LB as Cilium LB
  K->>Pod: SIGTERM (begin termination)
  K->>EP: remove pod IP from endpoints
  LB->>LB: stop sending NEW connections
  Pod->>Pod: preStop hook + finish in-flight requests
  Note over K,Pod: terminationGracePeriodSeconds countdown (default 30s)
  Pod-->>K: exits cleanly
  K->>Pod: SIGKILL only if grace period expires
""" 

# ===========================================================================
# CHAPTER 19 — RBAC & Service Accounts
# ===========================================================================

DIAGRAMS["19-rbac-model"] = T + """
flowchart LR
  subgraph SUBJ["Subjects (who)"]
    U["User / Group<br/>(humans via kubeconfig)"]:::user
    SA["ServiceAccount<br/>(workloads)"]:::svc
  end
  RB["RoleBinding /<br/>ClusterRoleBinding<br/>(grants)"]:::edge
  R["Role / ClusterRole<br/>(verbs on resources)<br/>get,list,watch,create..."]:::plat
  RES["API resources<br/>pods, secrets, deployments"]:::data
  U --> RB
  SA --> RB
  RB --> R --> RES
  NOTE["RBAC = Subject -> Binding -> Role -> allowed verbs on resources.<br/>Roles are namespaced, ClusterRoles are cluster-wide. Additive only:<br/>no explicit deny, default is deny-all."]
""" + PALETTE

DIAGRAMS["19-serviceaccount"] = T + """
sequenceDiagram
  autonumber
  participant Pod as orders pod
  participant SA as ServiceAccount (orders-sa)
  participant API as kube-apiserver
  Pod->>SA: use projected token (auto-mounted)
  Pod->>API: request (Bearer token)
  API->>API: authenticate token -> orders-sa
  API->>API: RBAC: does orders-sa allow this verb?
  API-->>Pod: allowed (get configmaps) / denied (list secrets)
  Note over Pod,API: give each service its OWN SA with least-privilege Role
""" 

# ===========================================================================
# CHAPTER 20 — Pod Security Admission & SecurityContext
# ===========================================================================

DIAGRAMS["20-psa-levels"] = T + """
flowchart TB
  PRIV["privileged<br/>no restrictions<br/>only: falco, node agents"]:::data
  BASE["baseline<br/>blocks known escalations<br/>data namespace"]:::edge
  REST["restricted<br/>hardened: non-root, no caps,<br/>seccomp - app namespaces"]:::svc
  REST --> BASE --> PRIV
  NOTE["Three PSA levels enforced per NAMESPACE via labels. App namespaces<br/>run 'restricted'. Escalate only where a workload genuinely needs it."]
""" + PALETTE

DIAGRAMS["20-securitycontext"] = T + """
flowchart TB
  POD["Pod / Container securityContext"]:::plat
  POD --> A["runAsNonRoot: true<br/>runAsUser: 65532"]:::svc
  POD --> B["readOnlyRootFilesystem: true"]:::svc
  POD --> C["allowPrivilegeEscalation: false"]:::svc
  POD --> D["capabilities: drop ALL"]:::svc
  POD --> E["seccompProfile: RuntimeDefault"]:::svc
  NOTE["Defense in depth at the pod level: no root, immutable rootfs,<br/>no new privileges, drop all Linux capabilities, seccomp filter syscalls."]
""" + PALETTE

# ===========================================================================
# CHAPTER 21 — Network Policies (zero-trust with Cilium)
# ===========================================================================

DIAGRAMS["21-default-deny"] = T + """
flowchart TB
  subgraph NS["namespace tickethub (default-deny applied)"]
    FE["frontend"]:::svc
    GW["gateway"]:::svc
    OR["orders"]:::svc
    PAY["payments"]:::svc
  end
  DB[("postgres (data ns)")]:::data
  FE -->|"allow :8080"| GW
  GW -->|"allow :8080"| OR
  OR -->|"allow :8080"| PAY
  OR -->|"allow :5432"| DB
  FE -. "DENIED" .-> DB
  GW -. "DENIED" .-> PAY
  NOTE["Start with default-deny, then allow only required flows. frontend<br/>can reach gateway, not the DB. Every other path is blocked."]
""" + PALETTE

DIAGRAMS["21-policy-anatomy"] = T + """
flowchart LR
  POL["NetworkPolicy / CiliumNetworkPolicy"]:::edge
  POL --> SEL["podSelector: app=orders<br/>(who it applies to)"]:::plat
  POL --> ING["ingress FROM<br/>podSelector app=gateway :8080"]:::svc
  POL --> EG["egress TO<br/>app=postgres :5432<br/>+ DNS :53"]:::data
  NOTE["A policy selects target pods, then whitelists ingress sources and<br/>egress destinations by label + port. Cilium enforces it in eBPF,<br/>and can go L7 (allow only GET /api/orders)."]
""" + PALETTE

# ===========================================================================
# CHAPTER 22 — Kyverno (policy as code)
# ===========================================================================

DIAGRAMS["22-kyverno-admission"] = T + """
sequenceDiagram
  autonumber
  participant User as kubectl / CI
  participant API as kube-apiserver
  participant KV as Kyverno webhook
  User->>API: apply Pod (image: nginx:latest)
  API->>KV: admission review
  KV->>KV: VALIDATE (no :latest? runAsNonRoot?)
  KV->>KV: MUTATE (add default labels, seccomp)
  alt policy violated
    KV-->>API: DENY (block admission)
    API-->>User: error: image tag latest not allowed
  else compliant
    KV-->>API: ALLOW (mutated)
    API-->>User: created
  end
""" 

DIAGRAMS["22-policy-actions"] = T + """
flowchart TB
  KV["Kyverno ClusterPolicy"]:::edge
  KV --> V["validate<br/>reject bad specs<br/>(no latest, must have limits)"]:::data
  KV --> M["mutate<br/>inject defaults<br/>(labels, securityContext)"]:::svc
  KV --> G["generate<br/>create linked resources<br/>(default NetworkPolicy per ns)"]:::plat
  NOTE["Policy as code in plain YAML - no new language. validate blocks,<br/>mutate fixes, generate provisions. Run in Audit first, then Enforce."]
""" + PALETTE

# ===========================================================================
# CHAPTER 23 — Falco (runtime threat detection)
# ===========================================================================

DIAGRAMS["23-falco"] = T + """
flowchart LR
  SYS["Kernel syscalls<br/>(exec, open, connect)"]:::data --> EBPF["Falco eBPF probe<br/>(DaemonSet, all nodes)"]:::plat
  EBPF --> RULES["Falco rules engine<br/>suspicious behavior?"]:::edge
  RULES -->|"match"| ALERT["Alert<br/>shell in container,<br/>write to /etc, crypto-mine"]:::svc
  ALERT --> SINK["Falcosidekick -><br/>Slack / SIEM / Prometheus"]:::plat
  NOTE["Falco watches syscalls at runtime via eBPF. Rules flag behavior<br/>that policies can't catch statically: a shell spawned in a pod,<br/>unexpected outbound connection, writes to sensitive paths."]
""" + PALETTE

# ===========================================================================
# CHAPTER 24 — Secrets at rest, image signing, supply chain
# ===========================================================================

DIAGRAMS["24-encryption-at-rest"] = T + """
flowchart LR
  API["kube-apiserver"]:::edge --> ENC["EncryptionConfiguration<br/>(AES-GCM / KMS)"]:::plat
  ENC -->|"encrypt before write"| ETCD[("etcd<br/>ciphertext at rest")]:::data
  KMS["External KMS / Vault<br/>(key management)"]:::plat -.-> ENC
  NOTE["Without this, Secrets sit in etcd as base64 plaintext. EncryptionConfig<br/>encrypts them before write; a KMS provider keeps the key off the node."]
""" + PALETTE

DIAGRAMS["24-image-signing"] = T + """
sequenceDiagram
  autonumber
  participant CI
  participant Cosign as cosign
  participant Reg as Registry
  participant Adm as Admission (Kyverno/Connaisseur)
  participant K8s
  CI->>Cosign: sign image digest (private key)
  Cosign->>Reg: push signature alongside image
  K8s->>Adm: pod wants registry/orders@sha256
  Adm->>Reg: fetch signature
  Adm->>Adm: verify against public key
  alt valid signature
    Adm-->>K8s: ADMIT
  else missing/invalid
    Adm-->>K8s: DENY (unsigned image blocked)
  end
""" 

# ===========================================================================
# CHAPTER 25 — CRDs & Operators
# ===========================================================================

DIAGRAMS["25-crd-operator"] = T + """
flowchart LR
  CRD["CustomResourceDefinition<br/>extends the API<br/>kind: PostgresCluster"]:::plat
  CR["Custom Resource<br/>(desired state)<br/>replicas: 3, version: 16"]:::edge
  OP["Operator / controller<br/>reconcile loop"]:::svc
  REAL["Actual objects<br/>StatefulSet, Services, Secrets"]:::data
  CRD --> CR --> OP
  OP -->|"watch + reconcile"| REAL
  REAL -.->|"observe drift"| OP
  NOTE["A CRD teaches the API a new noun. An Operator is a controller that<br/>watches those objects and drives reality to match - encoding the ops<br/>knowledge of running Postgres/Kafka/Ceph as software."]
""" + PALETTE

DIAGRAMS["25-operator-pattern"] = T + """
flowchart TB
  subgraph LOOP["Reconcile loop (forever)"]
    OBS["OBSERVE<br/>read desired (CR) + actual"]:::svc
    DIFF["DIFF<br/>compute drift"]:::edge
    ACT["ACT<br/>create/update/delete to converge"]:::plat
    OBS --> DIFF --> ACT --> OBS
  end
  NOTE["Operators run the same control-loop pattern Kubernetes uses<br/>internally: continuously drive actual state toward declared state.<br/>TicketHub uses operators for Rook-Ceph, Postgres, Kafka, cert-manager."]
""" + PALETTE

# ===========================================================================
# CHAPTER 26 — Observability (Prometheus, Grafana, Loki, Hubble)
# ===========================================================================

DIAGRAMS["26-three-pillars"] = T + """
flowchart TB
  subgraph OBS["Three pillars of observability"]
    M["METRICS<br/>Prometheus<br/>numeric time-series<br/>(CPU, latency, error rate)"]:::svc
    L["LOGS<br/>Loki<br/>structured events<br/>(what happened)"]:::edge
    TR["TRACES<br/>Tempo / Hubble<br/>request path across services<br/>(where time went)"]:::plat
  end
  G["Grafana<br/>single pane of glass"]:::data
  M --> G
  L --> G
  TR --> G
  NOTE["Metrics tell you SOMETHING is wrong, logs tell you WHAT, traces tell<br/>you WHERE. Grafana unifies all three over the same time range."]
""" + PALETTE

DIAGRAMS["26-prometheus"] = T + """
flowchart LR
  subgraph TARGETS["Scrape targets (/metrics)"]
    APP["app pods"]:::svc
    NE["node-exporter (DaemonSet)"]:::plat
    KSM["kube-state-metrics"]:::plat
  end
  PROM["Prometheus<br/>pull scrape + TSDB"]:::edge
  APP --> PROM
  NE --> PROM
  KSM --> PROM
  PROM --> GRAF["Grafana dashboards"]:::data
  PROM --> AM["Alertmanager<br/>-> Slack / PagerDuty"]:::data
  NOTE["Prometheus PULLS /metrics on an interval, stores time-series, and<br/>evaluates alert rules. Alertmanager dedups/routes. Grafana visualizes."]
""" + PALETTE

DIAGRAMS["26-logging"] = T + """
flowchart LR
  PODS["pod stdout/stderr"]:::svc --> AGENT["Promtail / Alloy<br/>(DaemonSet, per node)"]:::plat
  AGENT -->|"labels + push"| LOKI["Loki<br/>log store (indexes labels)"]:::edge
  LOKI --> GRAF["Grafana<br/>LogQL query"]:::data
  NOTE["A per-node agent tails container logs, labels them (namespace, pod,<br/>app) and ships to Loki. Loki indexes only LABELS (cheap), not full text.<br/>Correlate logs with metrics by the same labels + timestamp."]
""" + PALETTE

DIAGRAMS["26-instrumentation"] = T + """
flowchart LR
  subgraph APP["orders pod (instrumented)"]
    CODE["handler + middleware"]:::svc
    MET["/metrics :9090<br/>counter + histogram"]:::plat
    CODE --> MET
  end
  PROM["Prometheus<br/>pull scrape"]:::edge
  COLL["OTel Collector<br/>batch + forward"]:::edge
  TEMPO["Tempo<br/>trace store"]:::data
  GRAF["Grafana<br/>metrics + traces + logs"]:::data
  MET -->|"scrape /metrics"| PROM
  CODE -->|"OTLP spans :4317"| COLL
  COLL --> TEMPO
  PROM --> GRAF
  TEMPO --> GRAF
  NOTE["The APP produces telemetry: it exposes /metrics for Prometheus to pull,<br/>and pushes trace spans over OTLP to the Collector -> Tempo. Metric names<br/>(http_requests_total) must match what the alert rules query."]
""" + PALETTE

# ===========================================================================
# CHAPTER 27 — Backup, DR, upgrades, node maintenance
# ===========================================================================

DIAGRAMS["27-velero"] = T + """
flowchart LR
  VELERO["Velero<br/>(scheduled backups)"]:::edge
  VELERO -->|"k8s resource manifests"| OBJ["Object store<br/>(Ceph RGW / S3)"]:::data
  VELERO -->|"CSI volume snapshots"| SNAP["PV snapshots"]:::data
  OBJ --> RESTORE["Restore<br/>to same or new cluster"]:::svc
  SNAP --> RESTORE
  NOTE["Velero backs up BOTH the API objects (Deployments, Secrets...) and<br/>the persistent volume data (via CSI snapshots) to object storage.<br/>Restore rebuilds workloads + data on a fresh cluster (DR)."]
""" + PALETTE

DIAGRAMS["27-node-drain"] = T + """
sequenceDiagram
  autonumber
  participant Admin
  participant API
  participant Node
  Admin->>API: kubectl cordon node-3
  Note over Node: marked unschedulable - no NEW pods
  Admin->>API: kubectl drain node-3 (respects PDBs)
  API->>Node: evict pods gracefully
  Node-->>API: pods rescheduled elsewhere (PDB keeps minAvailable)
  Admin->>Node: patch OS / upgrade kubelet / reboot
  Admin->>API: kubectl uncordon node-3
  Note over Node: schedulable again - pods flow back
""" 

DIAGRAMS["27-upgrade-order"] = T + """
flowchart LR
  ETCD["0. Back up etcd + Velero"]:::data --> CP["1. Upgrade control plane<br/>one node at a time<br/>kubeadm upgrade apply"]:::edge
  CP --> ADDON["2. Upgrade addons/CNI if needed"]:::plat
  ADDON --> W["3. Upgrade workers<br/>cordon-drain-upgrade-uncordon<br/>rolling, one at a time"]:::svc
  W --> VERIFY["4. Verify + monitor"]:::svc
  NOTE["Upgrade skew rule: control plane first, only ONE minor version ahead<br/>of kubelets. Always back up etcd before. Drain respects PDBs (Ch 17)."]
""" + PALETTE

# ===========================================================================
# CHAPTER 28 — GitOps with Argo CD
# ===========================================================================

DIAGRAMS["28-gitops-flow"] = T + """
flowchart LR
  DEV["Developer"]:::user -->|"git push / PR merge"| GIT["Git repo<br/>(desired state)"]:::edge
  GIT --> ARGO["Argo CD<br/>continuously reconciles"]:::plat
  ARGO -->|"apply"| CLUSTER["Cluster<br/>(actual state)"]:::svc
  CLUSTER -.->|"detect drift"| ARGO
  ARGO -.->|"auto-heal / self-sync"| CLUSTER
  NOTE["Git is the single source of truth. Argo CD pulls it and drives the<br/>cluster to match - no kubectl apply from laptops. Manual drift is<br/>detected and reverted. Rollback = git revert."]
""" + PALETTE

DIAGRAMS["28-sync-waves"] = T + """
flowchart TB
  ROOT["app-of-apps<br/>(root Application)"]:::edge
  ROOT --> W2["wave 2: Cilium CNI"]:::svc
  ROOT --> W3["wave 3: Rook-Ceph + SCs"]:::data
  ROOT --> W4["wave 4: MetalLB + Ingress"]:::plat
  ROOT --> W6["wave 6: security (Kyverno, Falco)"]:::plat
  ROOT --> W8["wave 8: data (Postgres, Kafka)"]:::data
  ROOT --> W9["wave 9: TicketHub apps"]:::svc
  NOTE["The bootstrap order from Ch 9 is encoded as Argo sync-waves. One root<br/>app manages child apps; lower waves sync first. The whole platform is<br/>reproducible from Git in the correct order."]
""" + PALETTE

# ===========================================================================
# CHAPTER 29 — End-to-end recap
# ===========================================================================

DIAGRAMS["29-request-journey"] = T + """
flowchart TB
  U["User buys a ticket<br/>https://tickethub.com/api/orders"]:::user
  U --> DNS["DNS -> MetalLB IP (Ch 7)"]:::edge
  DNS --> ING["Cilium Gateway + TLS (Ch 7,24)"]:::edge
  ING -->|"NetworkPolicy allows (Ch 21)"| GW["gateway pod<br/>RBAC SA, restricted PSA (Ch 19,20)"]:::svc
  GW --> OR["orders pod<br/>HPA-scaled (Ch 16)"]:::svc
  OR -->|"Cilium eBPF svc LB (Ch 6,12)"| PAY["payments pod<br/>PriorityClass critical (Ch 17)"]:::svc
  OR -->|"allowed :5432 only (Ch 21)"| DB[("postgres-0<br/>StatefulSet + Ceph PV (Ch 8,14)")]:::data
  OR -->|"publish event"| K[("Kafka<br/>KEDA scales notifications (Ch 16)")]:::data
  ALL["Observed: Prometheus + Loki + Hubble (Ch 26)<br/>Watched: Falco (Ch 23) - Delivered: Argo CD (Ch 28)"]:::plat
  NOTE["Every layer built across 29 chapters cooperates to serve one request<br/>securely, elastically, and observably."]
""" + PALETTE

DIAGRAMS["29-full-stack"] = T + """
flowchart TB
  L1["Bare metal -> KVM/Proxmox VMs (Ch 2)"]:::plat
  L2["12-node kubeadm HA cluster (Ch 3,5)"]:::plat
  L3["Cilium CNI + MetalLB + Gateway API + Rook-Ceph (Ch 6,7,8)"]:::edge
  L4["Namespaces + quotas + bootstrap order (Ch 9)"]:::edge
  L5["9 containerized services: Deploy/StatefulSet/DaemonSet (Ch 10-14)"]:::svc
  L6["Resources + autoscaling + scheduling + health (Ch 15-18)"]:::svc
  L7["RBAC + PSA + NetPol + Kyverno + Falco + supply-chain (Ch 19-25)"]:::data
  L8["Observability + backup/DR + GitOps (Ch 26-28)"]:::data
  L1 --> L2 --> L3 --> L4 --> L5 --> L6 --> L7 --> L8
  NOTE["The complete TicketHub stack, bottom to top: from physical hardware<br/>to GitOps-delivered, secured, observable microservices."]
""" + PALETTE

# ===========================================================================
# MANIFEST DOCS — one relationship diagram per repo/manifests/*.yaml file.
# Keyed "mf-<folder>-<name>"; embedded by the per-manifest README.md docs.
# ===========================================================================

DIAGRAMS["mf-00-namespaces"] = T + """
flowchart TB
  subgraph CLUSTER["Cluster — 5 namespaces (Ch 9, 20)"]
    direction LR
    TH["tickethub<br/>team=app<br/>PSA restricted"]:::svc
    DA["data<br/>team=data<br/>PSA baseline"]:::data
    PL["platform<br/>team=platform<br/>PSA baseline"]:::plat
    MO["monitoring<br/>team=platform<br/>PSA baseline"]:::plat
    SE["security<br/>team=platform<br/>PSA privileged"]:::edge
  end
  APP["App workloads +<br/>quota + netpol"]:::svc --> TH
  STORE["Postgres + Kafka"]:::data --> DA
  SEC["Falco (host access)"]:::edge --> SE
""" + PALETTE

DIAGRAMS["mf-00-quota-limits"] = T + """
flowchart LR
  RQ["ResourceQuota tickethub-quota<br/>cpu 40/80, mem 80/160Gi<br/>pods 200, pvc 50, LB 2"]:::plat
  LRG["LimitRange tickethub-defaults<br/>default 100m/128Mi<br/>max 4CPU/8Gi"]:::plat
  NS["namespace: tickethub"]:::svc
  POD["Every new Pod:<br/>gets defaults, then capped"]:::edge
  RQ --> NS
  LRG --> NS
  NS --> POD
""" + PALETTE

DIAGRAMS["mf-10-ceph-cluster"] = T + """
flowchart LR
  CC["CephCluster rook-ceph<br/>3 mon / 2 mgr<br/>worker-data-1/2/3 (nvme)"]:::plat
  BP["CephBlockPool replicapool<br/>replicated size 3"]:::data
  SC["StorageClass<br/>rook-ceph-block"]:::edge
  PVC["StatefulSet PVCs<br/>postgres / kafka"]:::data
  CC --> BP --> SC --> PVC
""" + PALETTE

DIAGRAMS["mf-10-cert-manager-issuers"] = T + """
flowchart LR
  ST["ClusterIssuer<br/>letsencrypt-staging"]:::plat
  PR["ClusterIssuer<br/>letsencrypt (prod)"]:::plat
  ING["Gateway tickethub<br/>annotation: cluster-issuer"]:::edge
  ACME["Let's Encrypt ACME<br/>HTTP-01 via Gateway HTTPRoute"]:::user
  SEC["Secret tickethub-tls"]:::data
  ING --> PR --> ACME
  ACME --> SEC --> ING
""" + PALETTE

DIAGRAMS["mf-10-ingress-tickethub"] = T + """
flowchart LR
  U["Client HTTPS"]:::user
  LB["MetalLB LB IP"]:::edge
  ING["Gateway tickethub<br/>listeners :80/:443<br/>TLS: tickethub-tls"]:::edge
  RT["HTTPRoute tickethub<br/>host tickethub.example.com"]:::edge
  FE["Service frontend:80"]:::svc
  GW["Service gateway:8080"]:::svc
  U --> LB --> ING --> RT
  RT -->|"/"| FE
  RT -->|"/api"| GW
""" + PALETTE

DIAGRAMS["mf-10-metallb-pool"] = T + """
flowchart LR
  POOL["IPAddressPool tickethub-pool<br/>10.20.0.100-200"]:::plat
  L2["L2Advertisement<br/>tickethub-l2"]:::edge
  SVC["Service type<br/>LoadBalancer"]:::svc
  NET["VLAN 20 (ARP)"]:::user
  POOL --> SVC
  L2 --> NET
  SVC -->|"external IP assigned"| NET
""" + PALETTE

DIAGRAMS["mf-10-registry-pull-secret"] = T + """
flowchart LR
  SA["ServiceAccount default<br/>ns: tickethub"]:::plat
  PS["imagePullSecret<br/>registry-internal"]:::data
  POD["Every pod in tickethub"]:::svc
  REG["registry.internal<br/>private registry"]:::edge
  POD -->|"inherits SA"| SA --> PS
  POD -->|"authenticated pull"| REG
""" + PALETTE

DIAGRAMS["mf-10-storageclasses"] = T + """
flowchart LR
  B["StorageClass rook-ceph-block<br/>RBD, Retain, WaitForFirstConsumer"]:::edge
  F["StorageClass rook-cephfs<br/>CephFS, Delete, RWX"]:::edge
  RBD["ceph rbd csi"]:::plat
  CFS["ceph cephfs csi"]:::plat
  PVCB["Block PVCs (postgres, kafka)"]:::data
  PVCF["Shared RWX PVCs"]:::data
  B --> RBD --> PVCB
  F --> CFS --> PVCF
""" + PALETTE

DIAGRAMS["mf-15-internal-ca"] = T + """
flowchart LR
  SS["ClusterIssuer<br/>selfsigned-root"]:::plat
  CA["Certificate tickethub-root-ca<br/>10y ECDSA"]:::edge
  SEC["Secret tickethub-root-ca<br/>ns cert-manager"]:::data
  ISS["ClusterIssuer<br/>tickethub-internal"]:::plat
  LEAF["Leaf certs (orders-tls)<br/>+ trust bundle"]:::svc
  SS --> CA --> SEC --> ISS --> LEAF
""" + PALETTE

DIAGRAMS["mf-15-orders-internal-cert"] = T + """
flowchart LR
  ISS["ClusterIssuer<br/>tickethub-internal"]:::plat
  CERT["Certificate orders-tls<br/>SAN orders.tickethub.svc<br/>*.orders-headless..."]:::edge
  SEC["Secret orders-tls"]:::data
  DEP["Deployment orders<br/>internal TLS cert"]:::svc
  ISS --> CERT --> SEC --> DEP
""" + PALETTE

DIAGRAMS["mf-15-trust-bundle"] = T + """
flowchart LR
  SRC["Secret tickethub-root-ca<br/>key tls.crt"]:::data
  B["Bundle tickethub-ca<br/>(trust-manager)"]:::plat
  CM["ConfigMap tickethub-ca<br/>key ca.crt — ALL namespaces"]:::edge
  POD["Pods mount ca.crt<br/>to trust internal TLS"]:::svc
  SRC --> B --> CM --> POD
""" + PALETTE

DIAGRAMS["mf-20-postgres-statefulset"] = T + """
flowchart LR
  SEC["Secret postgres-db<br/>key password"]:::plat
  STS["StatefulSet postgres<br/>3 replicas, postgres:16"]:::data
  PVC["PVC data per pod<br/>rook-ceph-block 20Gi"]:::data
  SVC["Service postgres<br/>headless :5432"]:::svc
  ORD["orders + db-migrate<br/>clients"]:::edge
  SEC --> STS
  STS --> PVC
  STS --> SVC
  ORD -->|":5432"| SVC
""" + PALETTE

DIAGRAMS["mf-20-kafka-statefulset"] = T + """
flowchart LR
  STS["StatefulSet kafka<br/>3 replicas, bitnami/kafka:3.7"]:::evt
  PVC["PVC data per pod<br/>rook-ceph-block 50Gi"]:::data
  SVC["Service kafka<br/>headless :9092"]:::svc
  CFG["orders-config<br/>KAFKA_BROKERS"]:::plat
  KEDA["KEDA notifications<br/>lag trigger"]:::edge
  STS --> PVC
  STS --> SVC
  CFG -->|"kafka-0..2.kafka.data:9092"| SVC
  KEDA -->|"consumer lag"| SVC
""" + PALETTE

DIAGRAMS["mf-30-catalog-deployment"] = T + """
flowchart LR
  CM["ConfigMap catalog-config<br/>envFrom"]:::plat
  DEP["Deployment catalog<br/>3 replicas :8080<br/>RollingUpdate maxUnavail 0"]:::svc
  SVC["Service catalog<br/>ClusterIP 80->8080"]:::edge
  HPA["HPA catalog"]:::plat
  PDB["PDB catalog<br/>minAvailable 2"]:::plat
  CM --> DEP --> SVC
  HPA -->|"scales"| DEP
  PDB -->|"protects"| DEP
""" + PALETTE

DIAGRAMS["mf-30-db-migrate-job"] = T + """
flowchart LR
  SEC["Secret orders-db<br/>DB_PASSWORD"]:::data
  JOB["Job orders-db-migrate<br/>migrate up<br/>backoffLimit 3, restart Never"]:::plat
  PG["Postgres (ns data)"]:::data
  SEC --> JOB
  JOB -->|"apply schema"| PG
""" + PALETTE

DIAGRAMS["mf-30-orders-deployment"] = T + """
flowchart LR
  CM["orders-config"]:::plat
  SEC["Secret orders-db"]:::data
  DEP["Deployment orders<br/>3 replicas http:8080 metrics:9090"]:::svc
  SVC["Service orders<br/>80->8080, 9090"]:::edge
  OTEL["otel-collector :4317"]:::evt
  SM["ServiceMonitor orders"]:::plat
  HPA["HPA orders"]:::plat
  CM --> DEP
  SEC --> DEP
  DEP --> SVC
  DEP -->|"traces"| OTEL
  SM -->|"scrape 9090"| DEP
  HPA -->|"scales"| DEP
""" + PALETTE

DIAGRAMS["mf-40-configmaps"] = T + """
flowchart LR
  OC["ConfigMap orders-config<br/>LOG_LEVEL, PAYMENTS_URL, KAFKA_BROKERS"]:::plat
  CC["ConfigMap catalog-config<br/>LOG_LEVEL, SEARCH_URL"]:::plat
  ORD["Deployment orders (envFrom)"]:::svc
  CAT["Deployment catalog (envFrom)"]:::svc
  OC --> ORD
  CC --> CAT
""" + PALETTE

DIAGRAMS["mf-40-external-secrets"] = T + """
flowchart LR
  VAULT["Vault (ClusterSecretStore<br/>vault-backend)"]:::user
  ES1["ExternalSecret orders-db<br/>ns tickethub"]:::plat
  ES2["ExternalSecret postgres-db<br/>ns data"]:::plat
  S1["Secret orders-db"]:::data
  S2["Secret postgres-db"]:::data
  C1["orders Deploy + migrate Job"]:::svc
  C2["postgres StatefulSet"]:::svc
  VAULT --> ES1 --> S1 --> C1
  VAULT --> ES2 --> S2 --> C2
""" + PALETTE

DIAGRAMS["mf-50-catalog-hpa"] = T + """
flowchart LR
  M["metrics-server<br/>CPU utilization"]:::plat
  HPA["HPA catalog<br/>min 3 / max 20<br/>target CPU 70%"]:::edge
  DEP["Deployment catalog"]:::svc
  M --> HPA -->|"adjust replicas"| DEP
""" + PALETTE

DIAGRAMS["mf-50-notifications-keda"] = T + """
flowchart LR
  KAFKA["Kafka topic ticket-events<br/>consumerGroup notifications"]:::evt
  SO["ScaledObject notifications<br/>min 0 / max 30<br/>lagThreshold 100"]:::edge
  DEP["Deployment notifications"]:::svc
  KAFKA -->|"consumer lag"| SO -->|"scale (incl. to zero)"| DEP
""" + PALETTE

DIAGRAMS["mf-50-orders-hpa-custom"] = T + """
flowchart LR
  SM["ServiceMonitor orders<br/>http_requests_total"]:::plat
  PA["prometheus-adapter<br/>-> http_requests_per_second"]:::plat
  HPA["HPA orders<br/>min 3 / max 30<br/>target 50 rps/pod"]:::edge
  DEP["Deployment orders"]:::svc
  SM --> PA --> HPA -->|"scales"| DEP
""" + PALETTE

DIAGRAMS["mf-50-pdb"] = T + """
flowchart LR
  DRAIN["Node drain / upgrade"]:::edge
  PDBC["PDB catalog<br/>minAvailable 2"]:::plat
  PDBO["PDB orders<br/>minAvailable 2"]:::plat
  CAT["catalog pods"]:::svc
  ORD["orders pods"]:::svc
  DRAIN -->|"blocked if <2"| PDBC --> CAT
  DRAIN -->|"blocked if <2"| PDBO --> ORD
""" + PALETTE

DIAGRAMS["mf-50-priorityclasses"] = T + """
flowchart TB
  PC1["payments-critical<br/>value 100000"]:::data
  PC2["standard-app<br/>value 1000 (default)"]:::svc
  PC3["batch-low<br/>value 100"]:::edge
  SCHED["Scheduler:<br/>higher value wins,<br/>preempts lower on pressure"]:::plat
  PC1 --> SCHED
  PC2 --> SCHED
  PC3 --> SCHED
""" + PALETTE

DIAGRAMS["mf-50-prometheus-adapter-config"] = T + """
flowchart LR
  PROM["Prometheus<br/>http_requests_total (counter)"]:::plat
  ADP["prometheus-adapter rule<br/>sum(rate(...[2m]))"]:::edge
  API["custom.metrics.k8s.io<br/>http_requests_per_second"]:::plat
  HPA["HPA orders"]:::svc
  PROM --> ADP --> API --> HPA
""" + PALETTE

DIAGRAMS["mf-50-search-vpa"] = T + """
flowchart LR
  HIST["usage history"]:::plat
  VPA["VPA search<br/>updateMode: Off<br/>(recommend only)"]:::edge
  REC["recommended<br/>requests/limits"]:::data
  DEP["Deployment search<br/>(applied manually)"]:::svc
  HIST --> VPA --> REC -.->|"human review"| DEP
""" + PALETTE

DIAGRAMS["mf-60-falco-rules"] = T + """
flowchart LR
  SYS["Kernel syscalls<br/>(every node)"]:::plat
  DS["Falco DaemonSet<br/>ns security (privileged)"]:::edge
  R1["Rule: shell in tickethub pod"]:::data
  R2["Rule: write to /etc /bin"]:::data
  ALERT["Alert / audit sink"]:::user
  SYS --> DS
  DS --> R1 --> ALERT
  DS --> R2 --> ALERT
""" + PALETTE

DIAGRAMS["mf-60-kyverno-policies"] = T + """
flowchart LR
  REQ["kubectl apply Pod"]:::user
  ADM["Kyverno admission webhook"]:::edge
  P1["disallow-latest-tag<br/>(enforce)"]:::data
  P2["add-default-securitycontext<br/>(mutate)"]:::plat
  P3["verify-image-signatures<br/>(cosign)"]:::data
  OK["Pod admitted"]:::svc
  REQ --> ADM
  ADM --> P1
  ADM --> P2
  ADM --> P3 --> OK
""" + PALETTE

DIAGRAMS["mf-60-network-policies"] = T + """
flowchart LR
  DENY["default-deny-all<br/>all pods ingress+egress"]:::data
  GW["gateway pods"]:::edge
  ORD["orders pods"]:::svc
  PAY["payments pods"]:::svc
  PG["postgres (ns data)"]:::data
  DNS["kube-dns :53"]:::plat
  GW -->|"ingress :8080"| ORD
  ORD -->|"egress :8080"| PAY
  ORD -->|"egress :5432"| PG
  ORD -->|"egress"| DNS
""" + PALETTE

DIAGRAMS["mf-60-orders-rbac"] = T + """
flowchart LR
  SA["ServiceAccount orders-sa<br/>automount: false"]:::plat
  RB["RoleBinding<br/>orders-reader-binding"]:::plat
  ROLE["Role orders-reader<br/>get/list/watch configmaps"]:::edge
  API["kube-apiserver (RBAC)"]:::data
  SA --> RB --> ROLE
  SA -->|"token"| API
  API -->|"allow configmaps read"| ROLE
""" + PALETTE

DIAGRAMS["mf-70-cert-expiry-rule"] = T + """
flowchart LR
  EXP["x509-certificate-exporter<br/>reads /etc/kubernetes/pki"]:::plat
  PROM["Prometheus<br/>x509_cert_not_after"]:::edge
  RULE["PrometheusRule<br/>certificate-expiry"]:::data
  AM["Alertmanager<br/>ExpiringSoon (<21d) / Expired"]:::user
  EXP --> PROM --> RULE --> AM
""" + PALETTE

DIAGRAMS["mf-70-node-exporter-daemonset"] = T + """
flowchart LR
  HOST["Host / (ro) -> /host"]:::plat
  DS["DaemonSet node-exporter<br/>hostNetwork :9100<br/>tolerations: Exists"]:::edge
  N1["every node<br/>(incl. tainted)"]:::svc
  PROM["Prometheus scrape"]:::data
  HOST --> DS --> N1
  DS -->|"node metrics"| PROM
""" + PALETTE

DIAGRAMS["mf-70-orders-monitoring"] = T + """
flowchart LR
  DEP["Deployment orders<br/>:9090 /metrics"]:::svc
  SM["ServiceMonitor orders<br/>interval 15s"]:::plat
  PROM["Prometheus"]:::edge
  RULE["PrometheusRule tickethub-slo<br/>error rate / p99 latency"]:::data
  AM["Alertmanager"]:::user
  DEP --> SM --> PROM --> RULE --> AM
""" + PALETTE

DIAGRAMS["mf-70-otel-collector-tempo"] = T + """
flowchart LR
  ORD["Deployment orders<br/>OTLP export"]:::svc
  OC["otel-collector (2 replicas)<br/>:4317 batch+memlimit"]:::edge
  TEMPO["tempo :4317<br/>trace storage"]:::data
  GRAF["Grafana / query :3200"]:::user
  ORD -->|"OTLP gRPC"| OC --> TEMPO --> GRAF
""" + PALETTE

DIAGRAMS["mf-70-velero-schedule"] = T + """
flowchart LR
  SCH["Schedule daily-tickethub<br/>0 2 * * * , ttl 30d"]:::plat
  NS1["ns tickethub"]:::svc
  NS2["ns data (Postgres/Kafka)"]:::data
  SNAP["CSI volume snapshots<br/>(Ceph)"]:::edge
  OBJ["object store<br/>(default location)"]:::user
  SCH --> NS1 --> OBJ
  SCH --> NS2 --> SNAP --> OBJ
""" + PALETTE

# ===========================================================================
# DB REPLICATION CRDs — Ch 14.6 + Ch 25.5
# ===========================================================================

DIAGRAMS["14-db-replication-arch"] = T + """
flowchart TB
  subgraph CR["PostgresReplicationCluster CR — tickethub-postgres (ns data)"]
    direction TB
    POOL["PgBouncer pool<br/>transaction mode<br/>rw-pool :5432 / ro-pool :5432"]:::edge
    subgraph CLUSTER["Postgres instances (StatefulSet)"]
      direction LR
      P["postgres-0<br/>PRIMARY<br/>read + write"]:::data
      S1["postgres-1<br/>STANDBY<br/>hot-standby (RO)"]:::svc
      S2["postgres-2<br/>STANDBY<br/>hot-standby (RO)"]:::svc
    end
    WAL["WAL archive sidecar<br/>→ Ceph S3<br/>s3://tickethub-wal/postgres"]:::plat
    PM["PodMonitor<br/>postgres_exporter :9187"]:::plat
  end
  APP["orders / db-migrate<br/>clients"]:::user
  PROM["Prometheus"]:::edge
  APP -->|"rw connection"| POOL
  POOL -->|"server pool → primary"| P
  POOL -->|"read-only pool → standbys"| S1
  POOL -->|"read-only pool → standbys"| S2
  P -->|"streaming WAL"| S1
  P -->|"streaming WAL"| S2
  P -->|"WAL segments"| WAL
  PM -->|"scrape"| PROM
  NOTE["1 primary + 2 hot standbys. quorum-sync: primary acks after 1 standby<br/>flushes. PgBouncer multiplexes 400 client conns into 25 server conns.<br/>WAL archive enables PITR recovery from any point in the past 7 days."]
""" + PALETTE

DIAGRAMS["14-streaming-replication"] = T + """
sequenceDiagram
  autonumber
  participant C  as App / PgBouncer
  participant P  as Primary (postgres-0)
  participant W1 as WAL Sender 1
  participant S1 as Standby-1 WAL Receiver
  participant S2 as Standby-2 WAL Receiver
  participant ARC as WAL Archive (Ceph S3)
  C->>P: BEGIN / DML statements
  P->>P: Write to shared buffer + WAL buffer
  P->>W1: Stream WAL segment (async)
  W1-->>S1: WAL data (TCP stream)
  W1-->>S2: WAL data (TCP stream)
  S1->>S1: Write to standby WAL file
  S2->>S2: Write to standby WAL file
  S1-->>P: flush ack (LSN position)
  Note over P,S1: synchronousMode=quorum → primary waits for this ack
  P-->>C: COMMIT confirmed (RPO = 0 for single-standby loss)
  S1->>S1: Apply WAL → replay on hot-standby
  S2->>S2: Apply WAL → replay on hot-standby
  P->>ARC: Archive completed WAL segment (async)
  Note over P,ARC: walArchive.enabled=true → PITR to any past second
"""

DIAGRAMS["25-db-replication-crd"] = T + """
flowchart LR
  subgraph CRDS["CRD layer (db.tickethub.io/v1alpha1)"]
    direction TB
    PGCRD["CRD<br/>PostgresReplicationCluster"]:::plat
    RSCRD["CRD<br/>ReplicationSlot"]:::plat
  end
  subgraph CRS["Custom Resources (desired state)"]
    direction TB
    PGCR["PostgresReplicationCluster<br/>tickethub-postgres<br/>instances:3, sync:quorum<br/>pooler:enabled, walArchive:enabled"]:::edge
    RSCR["ReplicationSlot<br/>tickethub-cdc-slot<br/>type:logical, plugin:pgoutput"]:::edge
  end
  subgraph OP["tickethub-db-operator (reconcile loop)"]
    direction TB
    OBS["OBSERVE desired CR<br/>+ actual cluster state"]:::svc
    DIFF["DIFF — topology, lag,<br/>primary health, slot state"]:::svc
    ACT["ACT — create/update/delete<br/>workload objects"]:::svc
    OBS --> DIFF --> ACT --> OBS
  end
  subgraph REAL["Real Kubernetes objects created by operator"]
    direction TB
    STS["StatefulSet<br/>postgres-0/1/2"]:::data
    RWSVC["Service rw-pool<br/>→ primary (role=primary)"]:::svc
    ROSVC["Service ro-pool<br/>→ standbys (role=standby)"]:::svc
    BNCR["Deployment pgbouncer<br/>2 replicas"]:::edge
    PM["PodMonitor"]:::plat
    RSLOT["Postgres logical slot<br/>tickethub-cdc-slot"]:::evt
  end
  PGCRD --> PGCR --> OP
  RSCRD --> RSCR --> OP
  OP -->|"reconcile"| STS & RWSVC & ROSVC & BNCR & PM & RSLOT
  STS -.->|"status drift"| OP
  NOTE["CRDs teach the API two new nouns. The operator encodes DBA knowledge:<br/>switchover, failover, slot retention, pooler config, WAL archiving — all<br/>driven from a single declarative PostgresReplicationCluster manifest."]
""" + PALETTE

DIAGRAMS["mf-20-postgres-replication-crd"] = T + """
flowchart LR
  SEC["Secret postgres-db<br/>(from ExternalSecret)"]:::plat
  S3SEC["Secret ceph-s3-creds<br/>(WAL archive creds)"]:::plat
  CRD["CRD PostgresReplication-<br/>Cluster + ReplicationSlot"]:::plat
  CR["CR tickethub-postgres<br/>+ cdc-slot"]:::edge
  OP["tickethub-db-operator"]:::svc
  STS["StatefulSet<br/>postgres-0/1/2"]:::data
  RWSVC["Service rw-pool :5432<br/>→ primary"]:::svc
  ROSVC["Service ro-pool :5432<br/>→ standbys"]:::svc
  POOL["Deployment pgbouncer<br/>2 replicas"]:::edge
  PM["PodMonitor"]:::plat
  SEC --> OP
  S3SEC --> OP
  CRD --> CR --> OP
  OP --> STS & RWSVC & ROSVC & POOL & PM
""" + PALETTE

