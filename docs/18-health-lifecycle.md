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


### 18.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **All three probe types use the same failure threshold logic** (`failureThreshold × periodSeconds`) but serve different purposes: liveness kills and restarts the container; readiness removes it from Service endpoints (no restart); startup suppresses liveness during the startup window. A wrong probe type causes the wrong behavior — a liveness probe that triggers during a traffic spike causes a restart cascade instead of graceful back-pressure.
    - **`preStop` hook runs concurrently with SIGTERM in some container runtimes**: the hook is not guaranteed to complete before SIGTERM is sent in all cases. If your shutdown sequence depends on the hook finishing first (e.g., draining a connection pool before accepting SIGTERM), add a `sleep` in the hook equal to your expected drain time as a belt-and-suspenders measure.
    - **Rolling update `maxSurge` and `maxUnavailable` are evaluated as a PAIR**: with `maxUnavailable: 0` and `maxSurge: 1`, the update creates one new pod and waits for it to pass readiness before killing one old pod. The deployment is always at full capacity — ideal for zero-downtime. With `maxUnavailable: 1` and `maxSurge: 0`, it kills one pod first, then creates a replacement — briefly drops below capacity.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Liveness probe too aggressive during GC pauses**: a JVM doing a full GC may pause for 5-10 seconds. If `liveness.timeoutSeconds: 1` and `failureThreshold: 3`, the container is killed after ~3 seconds of GC — causing a restart loop under load. Set `timeoutSeconds: 5` and `failureThreshold: 3` (15s total) for JVM services.
    - **Readiness probe checking downstream dependencies**: a readiness probe that calls `SELECT 1` on Postgres means a Postgres outage marks ALL orders pods as unready — removing them from the Service endpoint and returning 503 to users even though the pods themselves are healthy. Check local health only in readiness probes; check downstream health in separate alerts.
    - **`terminationGracePeriodSeconds: 0`** for "fast" rolling updates: this kills containers immediately on SIGTERM with no grace period. In-flight requests are dropped. Always allow enough time for connection draining: `terminationGracePeriodSeconds` ≥ the longest expected request duration + 5s buffer.

!!! question "Architect Considerations"
    1. **Startup probe vs `initialDelaySeconds`**: `initialDelaySeconds` is a blunt instrument — it delays all probes by a fixed time regardless of actual startup progress. `startupProbe` is smarter: it polls until the app is actually ready, then hands off to liveness/readiness. Always use `startupProbe` for services with variable startup times (JVM warm-up, schema migrations).
    2. **Probe granularity**: a `/healthz` endpoint that returns 200 is not meaningful if it doesn't actually test the service's ability to serve traffic. Define three layers: `/healthz` (process alive — for liveness), `/readyz` (can serve requests — for readiness, checks DB connection pool), `/startupz` (initialization complete — for startup probe).
    3. **Rolling update speed vs risk**: `maxUnavailable: 0, maxSurge: 1` is safest (never below capacity) but slowest (one pod at a time). `maxUnavailable: 25%, maxSurge: 25%` is 4× faster but briefly runs at 75% capacity. Size your `minReplicas` so that `replicas × (1 - maxUnavailable)` still meets your RPS SLO during rollout.
    4. **Blue/green vs rolling for schema-breaking changes**: a rolling deployment of a service with a breaking API change means old and new versions serve traffic simultaneously. If the API break is a response field rename, clients see inconsistency. Use blue/green (create a separate Deployment, switch Service selector atomically) for schema-breaking changes.
    5. **Canary with traffic splitting**: Argo Rollouts or Flagger can send 5% of traffic to the new version (canary) and automatically roll back if the error rate exceeds a threshold. This is the production-safe deployment strategy for TicketHub's payments path — zero-risk progressive delivery.

!!! success "Chapter 18 checklist — Part IV complete"
    - **startup / readiness / liveness** probes each defined for their distinct job.
    - Liveness tests **only the process**; dependency health lives in **readiness**.
    - Rollouts use **RollingUpdate + maxUnavailable: 0**; rollback is one command.
    - Apps handle **SIGTERM** and drain within `terminationGracePeriodSeconds`.
    - Result: **self-healing, zero-downtime** deploys and scale events.

    TicketHub is now reliable and elastic. **Part V** locks it down: RBAC, Pod Security,
    NetworkPolicy, Kyverno, Falco, and supply-chain security.

---
