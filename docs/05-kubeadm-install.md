## <a name="ch5"></a>5. Installing Kubernetes with kubeadm (HA Control Plane)

Part I gave us 12 prepared VMs and a network plan. Now we turn them into an actual Kubernetes cluster using **kubeadm** — the official, vendor-neutral bootstrapping tool. We build a **highly available** control plane from the start, because retrofitting HA later is painful.

### 5.1 The install, end to end

![kubeadm install flow](assets/diagrams/05-kubeadm-flow.png)

The sequence never changes: prep every node → `init` the first control-plane → install a CNI → join the other control-plane nodes → join workers → label/taint pools.

!!! mental "Mental model — founding a company"
    `kubeadm init` on cp-1 is **incorporating the company**: it creates the official
    seal (the cluster **CA**), the headquarters (etcd + apiserver), and issues a
    **join token** — like an employee badge template. Every other node "joins" by
    presenting that token and getting badges (certs) signed by the same CA.

### 5.2 Step 0 — container runtime on every node

Kubernetes doesn't run containers itself; it delegates to a **CRI runtime**. We use **containerd**:

```bash
# On EVERY node
apt-get update && apt-get install -y containerd
containerd config default | tee /etc/containerd/config.toml
# Use the systemd cgroup driver (must match kubelet)
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd && systemctl enable containerd

# Install the kube tooling (pin the version!)
apt-get install -y kubelet=1.30.* kubeadm=1.30.* kubectl=1.30.*
apt-mark hold kubelet kubeadm kubectl
```

!!! warning "The cgroup driver must match"
    `containerd` and `kubelet` must use the **same** cgroup driver (`systemd`). A
    mismatch causes kubelet to fail with cryptic errors and pods stuck in
    `CreateContainerError`. This is one of the most common kubeadm install failures.

### 5.3 Step 1 — initialize the first control-plane node

The critical flag is `--control-plane-endpoint`, pointing at the **VIP** (from Chapter 3), not cp-1's own IP. This is what makes HA possible.

```bash
# On cp-1
kubeadm init \
  --control-plane-endpoint "10.10.0.10:6443" \  # the HAProxy VIP
  --upload-certs \                                # share CA certs for other CP joins
  --pod-network-cidr "10.244.0.0/16" \            # matches Cilium (Ch 4)
  --service-cidr "10.96.0.0/12" \
  --skip-phases=addon/kube-proxy                  # Cilium replaces kube-proxy
```

What happens under the hood:

![kubeadm bootstrap sequence](assets/diagrams/05-bootstrap-sequence.png)

kubeadm runs preflight checks, generates the **cluster CA** and all component certificates (the cluster is its own **PKI** — a private certificate authority that signs an identity for every component and node; see the Chapter 0 primer, the Glossary, and **Chapter 7A** for the full certificate inventory, HA SANs, and renewal), starts etcd and the control-plane components as **static pods** (pods the kubelet runs directly from a file, not via the API server — Chapter 0), and prints the **join commands**.

```bash
# Set up kubectl access
mkdir -p $HOME/.kube && cp /etc/kubernetes/admin.conf $HOME/.kube/config
kubectl get nodes    # cp-1 shows NotReady — no CNI yet, that's expected
```

### 5.4 Step 2 — install the CNI (nodes go Ready)

Nodes stay `NotReady` until a network plugin is installed. We install **Cilium** (full detail in Chapter 6):

```bash
cilium install --version 1.16.1 \
  --set kubeProxyReplacement=true \
  --set ipam.mode=cluster-pool \
  --set ipam.operator.clusterPoolIPv4PodCIDRList=10.244.0.0/16
cilium status --wait
kubectl get nodes    # cp-1 now Ready
```

### 5.5 Step 3 — join the other control-plane nodes

```bash
# On cp-2 and cp-3 — note the --control-plane flag and certificate-key
kubeadm join 10.10.0.10:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <cert-key>
```

Now all three API servers sit behind the VIP; etcd forms a 3-member quorum.

### 5.6 Step 4 — join the workers, then label & taint

```bash
# On each worker
kubeadm join 10.10.0.10:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

```bash
# From cp-1 — organize the pools (Chapter 3)
kubectl label node worker-gen-{1..4} pool=general
kubectl label node worker-data-{1..3} pool=data
kubectl taint node worker-data-{1..3} data=true:NoSchedule
kubectl label node worker-infra-{1..2} pool=infra
kubectl taint node worker-infra-{1..2} infra=true:NoSchedule

# Zone = physical failure domain (rack). No cloud provider sets this on bare
# metal — do it by hand so topology spreads work (Chapter 3, 17).
kubectl label node worker-gen-1 worker-data-1 worker-infra-1 topology.kubernetes.io/zone=rack-a
kubectl label node worker-gen-2 worker-data-2 worker-infra-2 topology.kubernetes.io/zone=rack-b
kubectl label node worker-gen-3 worker-gen-4  worker-data-3  topology.kubernetes.io/zone=rack-c
```

After install, here's what runs where:

![Post-install component layout](assets/diagrams/05-component-layout.png)

!!! tip "Join tokens expire — regenerate on demand"
    The bootstrap token expires after 24h. To add a node later:

            kubeadm token create --print-join-command

    For a new **control-plane** node you also re-upload certs:

            kubeadm init phase upload-certs --upload-certs

### 5.7 Verifying a healthy cluster

```bash
kubectl get nodes -o wide                 # all 12 Ready
kubectl get pods -n kube-system           # control-plane static pods + cilium
kubectl get --raw='/readyz?verbose'       # apiserver health
kubectl -n kube-system exec etcd-cp-1 -- etcdctl endpoint health --cluster
```

!!! key "Architect's HA install principles"
    - Always `init` with `--control-plane-endpoint` = **VIP**, even for a single CP
      you plan to grow. You cannot add it cleanly afterwards.
    - **Pin** kubelet/kubeadm/kubectl versions and `apt-mark hold` them — accidental
      upgrades break clusters.
    - Match the **cgroup driver** across containerd and kubelet.
    - Keep the kubeadm config and join process **scripted/GitOps'd** so any node is
      reproducible (immutable infra from Chapter 2).

!!! success "Chapter 5 checklist"
    - containerd + pinned kube tools on all nodes; swap off; sysctls set.
    - `kubeadm init` on cp-1 with the **VIP** endpoint and correct CIDRs.
    - CNI installed → nodes **Ready**.
    - cp-2/cp-3 and all workers **joined**; pools **labeled + tainted**.
    - Cluster health verified (nodes, etcd quorum, apiserver readyz).

---
