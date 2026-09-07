"""
Fallback renderer for the DIY-vs-OpenShift stack diagram (Ch 8A).

Canonical Mermaid source is in diagrams.py under '08b-openshift-stack'; run
render_diagrams.py with mermaid-cli to regenerate the canonical PNG. This
matplotlib script produces the PNG when Node/mermaid-cli is unavailable.

Usage: python render_openshift_diagram.py
"""
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = pathlib.Path(__file__).parent / "assets" / "diagrams" / "08b-openshift-stack.png"

PALETTE = {
    "edge": ("#ffedd5", "#c2410c", "#7c2d12"),
    "svc":  ("#dcfce7", "#15803d", "#14532d"),
    "data": ("#fee2e2", "#b91c1c", "#7f1d1d"),
    "plat": ("#ede9fe", "#6d28d9", "#4c1d95"),
}


def box(ax, cx, cy, w, h, text, kind, fontsize=11):
    fill, stroke, txt = PALETTE[kind]
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.10",
        linewidth=1.7, edgecolor=stroke, facecolor=fill, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", color=txt,
            fontsize=fontsize, zorder=3)


def column(ax, cx, title, title_color, rows):
    ax.add_patch(FancyBboxPatch(
        (cx - 3.0, 0.9), 6.0, 6.9,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.5, edgecolor=title_color, facecolor="#f7f9fc",
        linestyle=(0, (6, 3)), zorder=0))
    ax.text(cx, 7.45, title, ha="center", va="center",
            color=title_color, fontsize=13, fontweight="bold", zorder=1)
    y = 6.6
    prev = None
    for label, kind in rows:
        box(ax, cx, y, 5.4, 0.82, label, kind, fontsize=10.5)
        if prev is not None:
            ax.add_patch(FancyArrowPatch((cx, prev - 0.41), (cx, y + 0.41),
                         arrowstyle="-|>", mutation_scale=13, linewidth=1.3,
                         color="#64748b", zorder=1))
        prev = y
        y -= 1.0


fig, ax = plt.subplots(figsize=(16, 9))
ax.set_xlim(0, 16)
ax.set_ylim(0, 9)
ax.axis("off")

ax.text(8, 8.5, "Same platform, two bring-up paths: DIY stack (Ch 5\u20138) vs OpenShift",
        ha="center", va="center", fontsize=16, fontweight="bold", color="#12325c")

column(ax, 4.0, "DIY stack (Ch 5\u20138) \u2014 you assemble", "#6d28d9", [
    ("kubeadm HA control plane", "plat"),
    ("containerd runtime", "plat"),
    ("Cilium eBPF CNI + Hubble", "edge"),
    ("MetalLB + Cilium Gateway API", "edge"),
    ("cert-manager PKI", "svc"),
    ("Rook-Ceph storage", "data"),
])

column(ax, 12.0, "OpenShift \u2014 one installer bundles it", "#c2410c", [
    ("openshift-install (Agent-based)", "plat"),
    ("CRI-O runtime", "plat"),
    ("OVN-Kubernetes CNI", "edge"),
    ("MetalLB Operator + Router/Routes", "edge"),
    ("cert-manager Operator + serving certs", "svc"),
    ("OpenShift Data Foundation (Ceph)", "data"),
])

ax.add_patch(FancyArrowPatch((7.05, 4.3), (8.95, 4.3), arrowstyle="-|>",
             mutation_scale=20, linewidth=2.0, color="#15803d", zorder=4))
ax.text(8.0, 4.7, "same workloads:\nHelm chart + Argo CD + PSA/SCC",
        ha="center", va="center", fontsize=9.5, color="#14532d")

ax.add_patch(FancyBboxPatch((0.5, 0.15), 15.0, 0.6,
             boxstyle="round,pad=0.02,rounding_size=0.1",
             linewidth=1.1, edgecolor="#c4ccd8", facecolor="#eef3fb", zorder=0))
ax.text(8, 0.45,
        "DIY = best-of-breed parts you integrate and own.  OpenShift = one supported installer that "
        "pins and upgrades the whole stack.  TicketHub's chart and Argo CD apps run on both.",
        ha="center", va="center", fontsize=9.5, color="#2a3f5f")

fig.savefig(OUT, dpi=110, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
