## <a name="ch18"></a>18. Health & Lifecycle — Probes, Rollout Strategies & Graceful Shutdown

A pod that is *running* is not necessarily *working*, and a pod that is *stopping* shouldn't drop live requests. This chapter closes Part IV with the mechanisms that make TicketHub self-healing and zero-downtime: **probes** that tell Kubernetes the truth about pod health, **rollout strategies** that ship new versions without an outage, and **graceful shutdown** that finishes in-flight work.

### 18.1 Three probes, three different jobs

![Probes](assets/diagrams/18-probes.png)

| Probe | Question | On failure | Gates |
|-------|----------|-----------|-------|
| **startupProbe** | Has it booted yet? | Restart container | Protects slow starters from liveness |
| **readinessProbe** | Ready for traffic? | **Remove from Service** (no restart) | EndpointSlice membership |
| **livenessProbe** | Still alive/healthy? | **Restart** container | Self-healing |

```yaml
startupProbe:                    # give slow apps up to 30x2s = 60s to boot
  httpGet: { path: /healthz, port: 8080 }
  failureThreshold: 30
  periodSeconds: 2
readinessProbe:                  # only Ready pods get traffic
  httpGet: { path: /readyz, port: 8080 }
  initialDelaySeconds: 3
  periodSeconds: 5
livenessProbe:                   # restart if wedged
  httpGet: { path: /healthz, port: 8080 }
  initialDelaySeconds: 10
  periodSeconds: 10
```

!!! mental "Mental model — a new employee's first day"
    **startup** = "has the new hire finished orientation?" (don't judge them yet).
    **readiness** = "are they at their desk ready to take calls?" (route work only when
    yes). **liveness** = "have they passed out?" (if unresponsive, send them home and
    call a replacement). Three different questions — never answer them with one probe.

!!! key "readiness ≠ liveness — the classic outage"
    Point **liveness** at a check that also depends on the **database**, and a brief DB
    blip makes Kubernetes **restart every pod at once** — turning a small dependency hiccup
    into a full outage. Liveness must test only *this process*. Dependency health belongs
    in **readiness** (which just pauses traffic, no restart).

### 18.2 Rollout strategies

The default **RollingUpdate** replaces pods gradually; with `maxUnavailable: 0` there's never a capacity dip, and a failing new version **halts the rollout** automatically.

![Rollout](assets/diagrams/18-rollout.png)

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0        # add a Ready new pod BEFORE removing an old one
    maxSurge: 1
```

```bash
kubectl -n tickethub rollout status deploy/catalog     # watch convergence
kubectl -n tickethub rollout undo deploy/catalog       # instant rollback to prior ReplicaSet
```

| Strategy | How | When |
|----------|-----|------|
| **RollingUpdate** | Gradual pod-by-pod swap | Default for all services |
| **Recreate** | Kill all, then start new | Only when versions can't coexist |
| **Blue-Green** | Full parallel stack, flip traffic | High-risk releases (via Argo Rollouts) |
| **Canary** | Shift a % of traffic, watch metrics | Progressive delivery (Argo Rollouts, Ch 28) |

!!! tip "Readiness probes are what make rolling updates safe"
    `maxUnavailable: 0` only helps if "available" means truly *ready*. Because the new pod
    joins the Service **only after** its readiness probe passes, users are never routed to
    a half-booted pod. Rollout safety = readiness probe + `maxUnavailable: 0`.

### 18.3 Graceful shutdown

When a pod is removed (scale-down, rollout, drain), Kubernetes must not sever live connections. The termination sequence is precise:

![Graceful shutdown](assets/diagrams/18-graceful-shutdown.png)

1. Pod IP is removed from the **EndpointSlice** → no *new* connections routed.
2. Container receives **SIGTERM**; an optional **preStop** hook runs.
3. App finishes in-flight requests and exits within `terminationGracePeriodSeconds` (default 30s).
4. **SIGKILL** only if the grace period expires.

```yaml
terminationGracePeriodSeconds: 45
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]   # let endpoint removal propagate first
```

!!! warning "Handle SIGTERM in your app, or you drop requests"
    If the process ignores **SIGTERM** and just dies on SIGKILL, in-flight requests are
    cut mid-response every deploy. The app must catch SIGTERM, stop accepting new work,
    drain active requests, then exit. The `preStop sleep` covers the brief race between
    endpoint removal and the load balancer noticing.

!!! success "Chapter 18 checklist — Part IV complete"
    - **startup / readiness / liveness** probes each defined for their distinct job.
    - Liveness tests **only the process**; dependency health lives in **readiness**.
    - Rollouts use **RollingUpdate + maxUnavailable: 0**; rollback is one command.
    - Apps handle **SIGTERM** and drain within `terminationGracePeriodSeconds`.
    - Result: **self-healing, zero-downtime** deploys and scale events.

    TicketHub is now reliable and elastic. **Part V** locks it down: RBAC, Pod Security,
    NetworkPolicy, Kyverno, Falco, and supply-chain security.

---
