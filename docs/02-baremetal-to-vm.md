## <a name="ch2"></a>2. From Bare Metal to Virtual Machines

TicketHub runs in our own data center — there is no cloud "give me a node" button. As the architect, you start with **physical servers** and must turn them into the fleet of **VMs** that will become Kubernetes nodes. This chapter builds that foundation layer by layer.

### 2.1 The three layers

![Bare metal to VM layers](assets/diagrams/02-baremetal-to-vm.png)

| Layer | What it is | Our choice |
|-------|-----------|------------|
| **1. Physical (bare metal)** | Real servers: CPU sockets, RAM, NVMe disks, NICs | 3 × dual-socket servers, 256 GB RAM, NVMe |
| **2. Hypervisor** | Software that slices one physical host into many VMs | **KVM** via **Proxmox VE** |
| **3. Virtual machines** | The isolated "computers" that become k8s nodes | 12 VMs across the 3 hosts |

!!! mental "Mental model — an apartment building"
    A **bare-metal server** is a plot of land. The **hypervisor** is the construction
    company that builds an apartment building on it. Each **VM** is an apartment —
    isolated, with its own allotted space (vCPU, RAM, disk), sharing the underlying
    plumbing (physical hardware). Kubernetes then moves its "tenants" (pods) into
    those apartments.

### 2.2 Why virtualize at all? Why not run Kubernetes on bare metal directly?

You *can* run Kubernetes directly on physical machines, but virtualization buys an architect crucial flexibility:

| Benefit | Why it matters for TicketHub |
|---------|------------------------------|
| **Right-sizing** | Carve a 256 GB host into differently-sized nodes (small control-plane, large data node) |
| **Isolation** | A misbehaving node VM can't take down the whole physical host |
| **Fast rebuild** | Re-provision a node VM from a template in minutes (immutable infra) |
| **Live migration** | Move a VM to another host for hardware maintenance with no downtime |
| **Density** | Run 3–4 nodes per physical host instead of wasting a whole server on one node |

!!! note "The trade-off: a small performance tax"
    Virtualization adds ~2–5% overhead and a layer to debug. For latency-critical
    or storage-heavy nodes you can mitigate with **CPU pinning**, **huge pages**, and
    **NVMe passthrough** (giving a VM direct access to a physical disk) — which we do
    for the **data** node pool.

### 2.3 Slicing one host into nodes

Here's how a single 256 GB / 64 vCPU physical host is divided into cluster-node VMs:

![VM slicing of one host](assets/diagrams/02-vm-slicing.png)

**Sizing guidance an architect applies:**

| VM role | vCPU | RAM | Disk | Overcommit? |
|---------|------|-----|------|-------------|
| Control-plane | 4 | 8 GB | 50 GB SSD | **No** — etcd is latency-sensitive |
| Worker (general) | 8 | 32 GB | 100 GB | Light CPU overcommit OK |
| Worker (data) | 12 | 64 GB | NVMe passthrough | **No** — storage & DB |
| Host reserve | — | ~16 GB | — | Never allocate 100% |

!!! warning "Never starve etcd, never allocate 100%"
    - **etcd** (on control-plane VMs) is extremely sensitive to disk and CPU latency.
      Give control-plane VMs **dedicated** (non-overcommitted) resources and fast SSD.
    - Always leave **host headroom** (RAM + CPU) for the hypervisor itself. Allocating
      every last GB to VMs causes swapping and cascading instability.

### 2.4 Spreading VMs across physical hosts (failure domains)

*Which* physical host each VM lands on is a critical availability decision. If all 3 control-plane VMs sat on one physical host, that host failing would **destroy etcd quorum** and take down the cluster's brain.

![VM placement across hosts](assets/diagrams/02-host-vm-placement.png)

!!! key "Failure-domain rule"
    Spread the **3 control-plane VMs across 3 different physical hosts**. Do the same
    for stateful replicas (Postgres primary/replica, Kafka brokers, Ceph OSDs). One
    physical host failure should cost you **at most one** member of any quorum or
    replica set. We'll enforce the pod-level half of this with **anti-affinity** and
    **topology spread** in Chapter 17.

### 2.5 Provisioning VMs as immutable templates

An architect doesn't hand-build 12 VMs. You build **one golden image** and clone it:

```bash
# On each Proxmox host: create a cloud-init Ubuntu template once...
qm create 9000 --name ubuntu-2204-template --memory 2048 --cores 2 \
  --net0 virtio,bridge=vmbr0
qm importdisk 9000 jammy-server-cloudimg-amd64.img local-nvme
qm set 9000 --scsihw virtio-scsi-pci --scsi0 local-nvme:vm-9000-disk-0
qm set 9000 --ide2 local-nvme:cloudinit --boot c --bootdisk scsi0 --serial0 socket
qm template 9000

# ...then clone a right-sized worker from it in seconds
qm clone 9000 210 --name worker-gen-1 --full
qm set 210 --cores 8 --memory 32768
qm resize 210 scsi0 100G
qm start 210
```

!!! tip "Immutable infrastructure"
    Treat node VMs as **cattle, not pets**. Never hand-patch a node in place — if it
    misbehaves, `kubectl drain` it, delete the VM, and clone a fresh one from the
    template. Everything reproducible lives in the template + `kubeadm` config +
    GitOps (Chapter 28). This is the foundation of a maintainable cluster.

### 2.6 Base OS preparation (every node)

Whatever tool provisions the VMs, every node needs the same kernel-level prep before `kubeadm` (Chapter 5). Foreshadowing the install:

```bash
# Kubernetes requires swap OFF
swapoff -a && sed -i '/ swap / s/^/#/' /etc/fstab

# Kernel modules + sysctls for container networking (Cilium)
modprobe overlay && modprobe br_netfilter
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system
```

!!! success "Chapter 2 checklist"
    - Physical hosts chosen and sized (3 × 256 GB/64 vCPU).
    - Hypervisor (KVM/Proxmox) installed on each.
    - A **golden VM template** built; nodes cloned and right-sized per role.
    - VMs **spread across hosts** to protect quorums (failure domains).
    - Base OS prep (swap off, modules, sysctls) baked into the template.

    Next: how these 12 VMs are organized into a **cluster topology** of control-plane
    and worker pools.

---
