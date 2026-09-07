"""
Fallback renderer for the OpenShift chapter diagrams (Ch 8A).

Canonical Mermaid sources live in diagrams.py under the '08b-*' keys; run
render_diagrams.py with mermaid-cli to regenerate the canonical PNGs. This
matplotlib script produces them when Node/mermaid-cli is unavailable, using the
shared color palette.

Usage: python render_openshift_diagram.py
"""
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT_DIR = pathlib.Path(__file__).parent / "assets" / "diagrams"

PALETTE = {
    "user": ("#dbeafe", "#1d4ed8", "#1e3a8a"),
    "edge": ("#ffedd5", "#c2410c", "#7c2d12"),
    "svc":  ("#dcfce7", "#15803d", "#14532d"),
    "data": ("#fee2e2", "#b91c1c", "#7f1d1d"),
    "plat": ("#ede9fe", "#6d28d9", "#4c1d95"),
}


def box(ax, cx, cy, w, h, text, kind, fontsize=11, cyl=False):
    fill, stroke, txt = PALETTE[kind]
    style = "round,pad=0.02,rounding_size=0.30" if cyl else "round,pad=0.02,rounding_size=0.10"
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h, boxstyle=style,
        linewidth=1.7, edgecolor=stroke, facecolor=fill, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", color=txt,
            fontsize=fontsize, zorder=3)


def arrow(ax, p1, p2, color="#475569", dashed=False, label=None, mid_dy=0.32, rad=0.0):
    ax.add_patch(FancyArrowPatch(
        p1, p2, arrowstyle="-|>", mutation_scale=15, linewidth=1.6, color=color,
        zorder=1, linestyle="--" if dashed else "-",
        connectionstyle=f"arc3,rad={rad}"))
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2 + mid_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=8.5, color=color)


def note(ax, x0, y0, w, text, fontsize=9.5):
    ax.add_patch(FancyBboxPatch((x0, y0), w, 0.7,
                 boxstyle="round,pad=0.02,rounding_size=0.1",
                 linewidth=1.1, edgecolor="#c4ccd8", facecolor="#eef3fb", zorder=0))
    ax.text(x0 + w / 2, y0 + 0.35, text, ha="center", va="center",
            fontsize=fontsize, color="#2a3f5f")


def title(ax, x, y, text):
    ax.text(x, y, text, ha="center", va="center", fontsize=15.5,
            fontweight="bold", color="#12325c")


def new_ax(w, h, xlim, ylim):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, xlim)
    ax.set_ylim(0, ylim)
    ax.axis("off")
    return fig, ax


def save(fig, name):
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def render_stack():
    fig, ax = new_ax(16, 9, 16, 9)
    title(ax, 8, 8.5, "Same platform, two bring-up paths: DIY stack (Ch 5\u20138) vs OpenShift")

    def column(cx, ttl, color, rows):
        ax.add_patch(FancyBboxPatch((cx - 3.0, 0.9), 6.0, 6.9,
                     boxstyle="round,pad=0.02,rounding_size=0.15", linewidth=1.5,
                     edgecolor=color, facecolor="#f7f9fc", linestyle=(0, (6, 3)), zorder=0))
        ax.text(cx, 7.45, ttl, ha="center", va="center", color=color,
                fontsize=13, fontweight="bold", zorder=1)
        y, prev = 6.6, None
        for label, kind in rows:
            box(ax, cx, y, 5.4, 0.82, label, kind, fontsize=10.5)
            if prev is not None:
                arrow(ax, (cx, prev - 0.41), (cx, y + 0.41), color="#64748b")
            prev = y
            y -= 1.0

    column(4.0, "DIY stack (Ch 5\u20138) \u2014 you assemble", "#6d28d9", [
        ("kubeadm HA control plane", "plat"), ("containerd runtime", "plat"),
        ("Cilium eBPF CNI + Hubble", "edge"), ("MetalLB + Cilium Gateway API", "edge"),
        ("cert-manager PKI", "svc"), ("Rook-Ceph storage", "data")])
    column(12.0, "OpenShift \u2014 one installer bundles it", "#c2410c", [
        ("openshift-install (Agent-based)", "plat"), ("CRI-O runtime", "plat"),
        ("OVN-Kubernetes CNI", "edge"), ("MetalLB Operator + Router/Routes", "edge"),
        ("cert-manager Operator + serving certs", "svc"),
        ("OpenShift Data Foundation (Ceph)", "data")])

    ax.add_patch(FancyArrowPatch((7.05, 4.3), (8.95, 4.3), arrowstyle="-|>",
                 mutation_scale=20, linewidth=2.0, color="#15803d", zorder=4))
    ax.text(8.0, 4.7, "same workloads:\nHelm chart + Argo CD + PSA/SCC",
            ha="center", va="center", fontsize=9.5, color="#14532d")
    note(ax, 0.5, 0.15, 15.0,
         "DIY = best-of-breed parts you integrate and own.  OpenShift = one supported installer that "
         "pins and upgrades the whole stack.  TicketHub's chart and Argo CD apps run on both.")
    save(fig, "08b-openshift-stack")


def render_agent_flow():
    fig, ax = new_ax(18, 6, 18, 6)
    title(ax, 9, 5.5, "Agent-based bare-metal install \u2014 two files and one ISO")
    steps = [
        ("install-config.yaml\n+ agent-config.yaml", "edge"),
        ("openshift-install\nagent create image", "plat"),
        ("agent.iso\nUSB / PXE / media", "svc"),
        ("boot all nodes\nfrom the ISO", "edge"),
        ("rendezvous node\nbootstraps etcd", "plat"),
        ("auto: control plane\nOVN CNI + registry\n+ monitoring", "svc"),
        ("wait-for\ninstall-complete", "plat"),
        ("console URL\n+ kubeadmin", "data"),
    ]
    n = len(steps)
    x0, x1, cy = 1.4, 16.6, 3.4
    xs = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]
    for x, (label, kind) in zip(xs, steps):
        box(ax, x, cy, 1.95, 1.5, label, kind, fontsize=8.8)
    for i in range(n - 1):
        arrow(ax, (xs[i] + 0.98, cy), (xs[i + 1] - 0.98, cy), color="#64748b")
    note(ax, 0.8, 0.5, 16.4,
         "Two config files and one ISO replace the entire Ch 5 kubeadm sequence \u2014 "
         "the CNI, internal registry and monitoring install themselves during bring-up.")
    save(fig, "08b-agent-install-flow")


def render_scc():
    fig, ax = new_ax(14, 8, 14, 8)
    title(ax, 7, 7.5, "One hardened Pod, two admission models \u2014 both admit it")
    box(ax, 7, 6.1, 8.2, 1.1,
        "Same hardened Pod\nrunAsNonRoot \u2022 drop ALL caps \u2022 seccomp RuntimeDefault \u2022 read-only rootfs",
        "svc", fontsize=9.6)
    box(ax, 3.4, 3.9, 4.8, 1.15, "DIY: PSA namespace label\nenforce = restricted", "plat", fontsize=10)
    box(ax, 10.6, 3.9, 4.8, 1.15, "OpenShift: SCC restricted-v2\nassigns a random high UID", "plat", fontsize=10)
    arrow(ax, (5.6, 5.55), (3.7, 4.5), color="#64748b")
    arrow(ax, (8.4, 5.55), (10.3, 4.5), color="#64748b")
    box(ax, 3.4, 1.8, 3.6, 1.0, "ADMITTED", "edge", fontsize=11)
    box(ax, 10.6, 1.8, 3.6, 1.0, "ADMITTED\nruns as random UID", "edge", fontsize=10)
    arrow(ax, (3.4, 3.32), (3.4, 2.3), color="#15803d")
    arrow(ax, (10.6, 3.32), (10.6, 2.3), color="#15803d")
    note(ax, 0.6, 0.3, 12.8,
         "The pod hardcodes no UID, so it passes BOTH models unchanged. "
         "A fixed runAsUser: 1000 would be rejected by SCC \u2014 prefer runAsNonRoot.")
    save(fig, "08b-scc-vs-psa")


def render_tickethub_ocp():
    fig, ax = new_ax(17, 8.5, 17, 8.5)
    title(ax, 8.5, 8.0, "TicketHub on OpenShift \u2014 same chart, only the edge & storage differ")
    box(ax, 4.0, 6.6, 4.2, 1.2, "OpenShift GitOps (Argo CD)\nrenders the Helm chart", "plat", fontsize=10)
    box(ax, 11.5, 6.6, 4.6, 1.2, "Project: tickethub\nDeployments + Services", "svc", fontsize=10)
    arrow(ax, (6.1, 6.6), (9.2, 6.6), color="#6d28d9", label="sync")

    box(ax, 2.2, 3.4, 3.0, 1.4, "User\ntickethub.example.com", "user", fontsize=9.8)
    box(ax, 6.0, 3.4, 3.0, 1.4, "Route\nHAProxy Router\nTLS edge", "edge", fontsize=9.5)
    box(ax, 9.6, 3.4, 2.6, 1.4, "gateway\nService", "svc", fontsize=10)
    box(ax, 12.9, 3.4, 2.9, 1.4, "orders / catalog\n\u2026 9 services", "svc", fontsize=9.3)
    box(ax, 15.6, 3.4, 2.4, 1.4, "ODF Ceph\nPVCs", "data", fontsize=9.5, cyl=True)
    arrow(ax, (3.7, 3.4), (4.5, 3.4), color="#475569")
    arrow(ax, (7.5, 3.4), (8.3, 3.4), color="#475569")
    arrow(ax, (10.9, 3.4), (11.45, 3.4), color="#475569")
    arrow(ax, (14.35, 3.4), (14.4, 3.4), color="#475569")
    arrow(ax, (11.5, 6.0), (10.0, 4.15), color="#15803d", dashed=True, label="creates", mid_dy=0.3, rad=-0.2)
    note(ax, 0.8, 0.5, 15.4,
         "The same Helm chart and Argo CD app-of-apps as the DIY stack. Only the edge object "
         "(Route instead of Gateway API) and the StorageClass (ODF) change.")
    save(fig, "08b-tickethub-on-ocp")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    render_stack()
    render_agent_flow()
    render_scc()
    render_tickethub_ocp()


if __name__ == "__main__":
    main()
