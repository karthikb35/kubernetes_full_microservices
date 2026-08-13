## <a name="ch15"></a>15. Resource Management — Requests, Limits, QoS, LimitRange & ResourceQuota

Chapter 9 introduced the resource *model*; now we make it operational. Getting **requests and limits** right is the single biggest lever on cluster stability and cost. Set them too low and pods get throttled or OOM-killed; too high and you waste half the cluster. This chapter turns TicketHub's raw capacity into predictable, fair, protected service.

### 15.1 Requests vs. limits — two different jobs

![Requests vs limits](assets/diagrams/15-requests-limits.png)

| | **Requests** | **Limits** |
|--|-------------|-----------|
| Meaning | Reserved, guaranteed amount | Hard ceiling |
| Used by | The **scheduler** (placement) | The **kubelet/cgroups** (runtime) |
| CPU over it | Impossible (it's reserved) | **Throttled** (compressible) |
| Memory over it | Impossible | **OOMKilled** (incompressible) |

```yaml
resources:
  requests: { cpu: "150m", memory: 192Mi }   # scheduler reserves this
  limits:   { cpu: "750m", memory: 768Mi }   # runtime cap
```

!!! mental "Mental model — a hotel reservation vs. the fire-code limit"
    The **request** is your **guaranteed reserved room** — the hotel (scheduler) won't
    overbook it. The **limit** is the **fire-code max occupancy** — exceed it on CPU and
    security throttles the party; exceed it on memory and the room is evacuated
    (OOMKilled). CPU is *compressible* (slow you down); memory is *incompressible* (evict).

### 15.2 Quality of Service classes

Kubernetes derives a **QoS class** from your requests/limits, and uses it to decide **who gets evicted first** when a node runs out of memory.

![QoS classes](assets/diagrams/15-qos-classes.png)

| QoS class | Condition | Eviction order |
|-----------|-----------|----------------|
| **Guaranteed** | requests == limits (both set, every container) | Evicted **last** |
| **Burstable** | at least one request set, but ≠ limits | Middle |
| **BestEffort** | no requests/limits at all | Evicted **first** |

!!! key "Give revenue-critical services Guaranteed QoS"
    Set `requests == limits` for **payments**, **orders**, and the **databases** so they
    land in the **Guaranteed** class and are the *last* to be evicted under node memory
    pressure. Leave elastic, non-critical work (search reindex, batch reports) Burstable.
    Never run production services as **BestEffort** — they're first out the door.

### 15.3 How to actually pick the numbers

1. Start from observed usage (Prometheus, `kubectl top`, VPA in *recommend* mode — Chapter 16).
2. **Requests** ≈ steady-state P50–P75 usage (so the scheduler packs efficiently).
3. **Memory limit** ≈ P99 + headroom (OOM is fatal, be generous).
4. **CPU limit** — often set generously or omitted for latency-sensitive services (throttling adds latency); always keep the **request** accurate.

!!! note "Reading percentiles (P50, P95, P99)"
    A **percentile** is the value below which that fraction of samples fall: **P50** (the
    median) is typical usage; **P99** is a near-worst case ("99% of samples are below
    this"). Size **memory limits** near **P99 + headroom** (an OOM kill is fatal), but set
    **requests** near **P50–P75** so the scheduler packs nodes efficiently for the common case.

!!! warning "A missing memory request is a scheduling landmine"
    A container with **no memory request** is treated as needing ~zero, so the scheduler
    packs nodes to the brim — then the first real memory spike triggers cascading
    **OOMKills** and evictions. Always set memory requests; enforce it with a LimitRange.

### 15.4 Guardrails: LimitRange and ResourceQuota

Individual specs can't be trusted to be complete, so the namespace enforces guardrails (introduced in Chapter 9, applied here):

![Quota and LimitRange](assets/diagrams/15-quota-limitrange.png)

- **LimitRange** injects **default** requests/limits into any container that omits them, and sets per-container **min/max**.
- **ResourceQuota** caps the **total** requests/limits/object-counts for the whole namespace, rejecting at admission anything that would exceed the budget.

```yaml
# already in repo/manifests/00-namespaces/quota-limits.yaml
apiVersion: v1
kind: LimitRange
metadata: { name: tickethub-defaults, namespace: tickethub }
spec:
  limits:
    - type: Container
      default:        { cpu: "500m", memory: 512Mi }   # limit if omitted
      defaultRequest: { cpu: "100m", memory: 128Mi }   # request if omitted
      max:            { cpu: "4",    memory: 8Gi }      # nobody hogs a whole node
```

```bash
kubectl -n tickethub describe quota tickethub-quota    # see used vs hard
kubectl -n tickethub top pods                          # live usage vs requests
```

!!! success "Chapter 15 checklist"
    - Every container has **memory requests** (and usually CPU requests) set deliberately.
    - Critical services set `requests == limits` → **Guaranteed** QoS.
    - **LimitRange** guarantees no container is unbounded; **ResourceQuota** caps each namespace.
    - Numbers derived from **real usage** (Prometheus/VPA-recommend), not guesses.
    - No production **BestEffort** pods.

---
