"""
Fallback renderer for the CI/CD -> GitOps promotion flow diagram (Ch 28).

The canonical Mermaid source lives in diagrams.py under key
'28-cicd-promotion-flow'; run render_diagrams.py with mermaid-cli available to
regenerate the canonical PNG. This matplotlib script produces the same PNG when
Node/mermaid-cli is not installed, using the shared color palette.

Usage: python render_cicd_diagram.py
"""
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = pathlib.Path(__file__).parent / "assets" / "diagrams" / "28-cicd-promotion-flow.png"

PALETTE = {
    "user": ("#dbeafe", "#1d4ed8", "#1e3a8a"),
    "edge": ("#ffedd5", "#c2410c", "#7c2d12"),
    "svc":  ("#dcfce7", "#15803d", "#14532d"),
    "data": ("#fee2e2", "#b91c1c", "#7f1d1d"),
    "plat": ("#ede9fe", "#6d28d9", "#4c1d95"),
    "evt":  ("#ccfbf1", "#0f766e", "#134e4a"),
}


def box(ax, cx, cy, w, h, text, kind, fontsize=11, bold=False):
    fill, stroke, txt = PALETTE[kind]
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.8, edgecolor=stroke, facecolor=fill, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", color=txt,
            fontsize=fontsize, fontweight="bold" if bold else "normal",
            zorder=3, wrap=True)


def arrow(ax, p1, p2, style="-|>", dashed=False, color="#475569", rad=0.0):
    ax.add_patch(FancyArrowPatch(
        p1, p2, arrowstyle=style, mutation_scale=16,
        linewidth=1.6, color=color, zorder=1,
        linestyle="--" if dashed else "-",
        connectionstyle=f"arc3,rad={rad}"))


def group(ax, x0, y0, x1, y1, label, color):
    ax.add_patch(FancyBboxPatch(
        (x0, y0), x1 - x0, y1 - y0,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.4, edgecolor=color, facecolor="#f7f9fc",
        linestyle=(0, (6, 3)), zorder=0))
    ax.text((x0 + x1) / 2, y1 - 0.32, label, ha="center", va="center",
            color=color, fontsize=11.5, fontweight="bold", zorder=1)


fig, ax = plt.subplots(figsize=(18.5, 9))
ax.set_xlim(0, 18.5)
ax.set_ylim(0, 9)
ax.axis("off")

ax.text(9.25, 8.6, "TicketHub delivery: CI build & sign  \u2192  GitOps promotion  \u2192  Argo CD rollout",
        ha="center", va="center", fontsize=16, fontweight="bold", color="#12325c")

# Developer
box(ax, 1.25, 4.6, 2.1, 1.3, "Developer\npush / PR\nto main", "user", bold=True)

# CI group
group(ax, 2.7, 1.2, 7.5, 7.8, "GitHub Actions CI  (no cluster credentials)", "#15803d")
ci_steps = [
    (6.9, "detect changed services", "edge"),
    (5.7, "build + test\n(Go, Python, frontend)", "svc"),
    (4.5, "validate manifests\n(kubeconform)", "svc"),
    (3.3, "build image\nghcr.io/\u2026/tickethub-svc", "svc"),
    (2.1, "cosign sign by digest", "plat"),
]
for cy, label, kind in ci_steps:
    box(ax, 5.1, cy, 4.1, 0.92, label, kind, fontsize=10.5)
for i in range(len(ci_steps) - 1):
    arrow(ax, (5.1, ci_steps[i][0] - 0.46), (5.1, ci_steps[i + 1][0] + 0.46))

# Promotion group
group(ax, 7.9, 2.6, 11.3, 6.6, "Promotion (GitOps write-back)", "#c2410c")
box(ax, 9.6, 5.4, 3.0, 0.95, "pin signed digest into\nsvc-deployment.yaml", "edge", fontsize=10.5)
box(ax, 9.6, 3.7, 3.0, 0.95, "open promotion PR\nreview \u2192 merge", "edge", fontsize=10.5)
arrow(ax, (9.6, 5.4 - 0.48), (9.6, 3.7 + 0.48))

# Git / Argo / K8s
box(ax, 12.7, 4.6, 2.0, 1.3, "Git main\n(desired state)", "edge", bold=True)
box(ax, 15.0, 4.6, 2.0, 1.5, "Argo CD\napp-of-apps\nsync waves 1\u20139", "plat", bold=True)
box(ax, 17.3, 4.6, 2.1, 1.7, "Kubernetes\nrolling update\n+ probes\n+ Kyverno verify", "svc", bold=True)

# Cross-stage arrows
arrow(ax, (2.3, 4.6), (3.05, 6.9))                    # dev -> detect
arrow(ax, (7.15, 2.1), (8.1, 3.7))                    # sign -> PR area (rewrite happens first)
arrow(ax, (11.3, 3.9), (11.7, 4.6))                   # PR -> git
arrow(ax, (13.7, 4.6), (14.0, 4.6))                   # git -> argo
arrow(ax, (16.0, 4.6), (16.25, 4.6))                  # argo -> k8s
ax.text(16.12, 5.15, "apply pinned\ndigest", ha="center", va="center",
        fontsize=8.5, color="#475569")
arrow(ax, (17.3, 5.45), (15.0, 5.7), dashed=True, rad=-0.35)  # k8s -> argo drift
ax.text(16.0, 6.5, "drift detected \u2192 self-heal", ha="center", va="center",
        fontsize=8.5, color="#475569")

# Bottom note
ax.add_patch(FancyBboxPatch((0.4, 0.2), 17.7, 0.8,
             boxstyle="round,pad=0.02,rounding_size=0.1",
             linewidth=1.2, edgecolor="#c4ccd8", facecolor="#eef3fb", zorder=0))
ax.text(9.25, 0.6,
        "CI builds, tests and SIGNS images but holds no cluster credentials.  "
        "Promotion pins the signed digest in Git via a PR.  "
        "Argo CD pulls Git and rolls it out; Kyverno admits only signed images.  Rollback = git revert.",
        ha="center", va="center", fontsize=10, color="#2a3f5f")

fig.savefig(OUT, dpi=110, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
