## <a name="ch16"></a>16. Autoscaling — Metrics Server, HPA, VPA, Cluster Autoscaler & KEDA

TicketHub's load is spiky: a hot concert on-sale can 10× traffic in seconds, then fall quiet. Static replica counts either waste money at idle or fall over at peak. **Autoscaling** makes the platform elastic across four independent dimensions — replicas, pod size, event backlog, and node count.

### 16.1 The four autoscalers — different axes

![Autoscaler layers](assets/diagrams/16-autoscaler-layers.png)

| Autoscaler | Scales | Trigger | TicketHub example |
|-----------|--------|---------|-------------------|
| **HPA** | replica **count** (horizontal) | CPU / memory / custom metric | catalog 3→20 pods on CPU |
| **VPA** | per-pod **requests** (vertical) | historical usage | right-size search pods |
| **KEDA** | replicas from **events** | Kafka lag, queue depth | notifications drain a backlog |
| **Cluster Autoscaler** | **node** count | Pending pods | add worker VMs at peak |

!!! mental "Mental model — a restaurant at rush hour"
    **HPA** calls in **more waiters** (replicas). **VPA** decides each waiter needs
    **bigger trays** (requests). **KEDA** watches the **ticket rail** (event queue) and
    staffs to the backlog. **Cluster Autoscaler** **opens more tables** (nodes) when the
    floor is full. All four cooperate; none replaces the others.

### 16.2 Metrics Server — the prerequisite

HPA and `kubectl top` need live CPU/memory. **Metrics Server** scrapes each kubelet and serves the metrics API. Install it first (bootstrap step 7, Chapter 9) or HPA has nothing to read.

```bash
kubectl top nodes        # verify Metrics Server works before configuring HPA
kubectl top pods -n tickethub
```

### 16.3 Horizontal Pod Autoscaler

HPA runs a control loop: read the metric, compute desired replicas, scale the Deployment.

![HPA loop](assets/diagrams/16-hpa-loop.png)

```text
desiredReplicas = ceil( currentReplicas × currentMetric / targetMetric )
# e.g. 3 replicas at 82% CPU, target 70%:  ceil(3 × 82/70) = ceil(3.51) = 4
```

```yaml
# repo/manifests/50-scaling/catalog-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: catalog
  namespace: tickethub
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: catalog
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 70 }
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300    # scale down slowly to avoid flapping
```

!!! key "HPA needs accurate requests to work at all"
    HPA's CPU **utilization** is measured *against the request* (82% of the request, not of
    the node). If requests are wrong, HPA's math is wrong — it scales too early or too
    late. Chapters 15 and 16 are joined at the hip: **right-size first, then autoscale**.

### 16.4 Scaling on custom metrics — prometheus-adapter

The HPA above scales on CPU, which Metrics Server provides out of the box. But CPU is often the *wrong* signal — a checkout service can be CPU-idle while requests queue behind a slow database. You'd rather scale on a **business metric** like requests-per-second or p99 latency. HPA can do that — but **only if something serves those metrics through the `custom.metrics.k8s.io` API**, because HPA cannot query Prometheus directly.

That something is **prometheus-adapter**: it sits between Prometheus and the HPA, translating PromQL results into the custom-metrics API that HPA understands.

![Custom metrics HPA](assets/diagrams/16-custom-metrics.png)

This is where Chapter 26 pays off: the `orders` service already exposes `http_requests_total`, Prometheus already scrapes it — the adapter just makes it *autoscalable*. Install the adapter and give it a rule that turns the raw counter into a per-pod rate:

```yaml
# repo/manifests/50-scaling/prometheus-adapter-config.yaml
# Helm: prometheus-community/prometheus-adapter, this becomes its `rules.custom`.
rules:
  custom:
    - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: { resource: namespace }
          pod:       { resource: pod }
      name:
        matches: "http_requests_total"
        as: "http_requests_per_second"          # the metric HPA will ask for
      metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'
```

Now the HPA can target it. `type: Pods` averages the metric across pods and scales to hold that average:

```yaml
# repo/manifests/50-scaling/orders-hpa-custom.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: orders, namespace: tickethub }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: orders }
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Pods
      pods:
        metric: { name: http_requests_per_second }
        target: { type: AverageValue, averageValue: "50" }   # ~50 rps per pod
```

Verify the metric is actually being served before trusting the HPA:

```bash
kubectl get --raw \
  /apis/custom.metrics.k8s.io/v1beta1/namespaces/tickethub/pods/*/http_requests_per_second
```

!!! key "Custom metrics: HPA <- adapter <- Prometheus <- your /metrics"
    HPA never talks to Prometheus. The chain is: your app exposes `/metrics` (Chapter 26),
    Prometheus scrapes it, **prometheus-adapter** serves it on `custom.metrics.k8s.io`, and
    HPA reads *that* API. Break any link — no ServiceMonitor, no adapter rule — and the HPA
    silently reports `<unknown>` for the metric and won't scale.

!!! warning "Scale on a rate or ratio, never a raw counter"
    `http_requests_total` only ever increases — targeting it directly would scale to the
    moon and never come back. Always wrap counters in `rate(...)` (as the adapter rule
    does) so you scale on *current* load. The same applies to latency: use a
    `histogram_quantile` over a window, not a cumulative sum.

### 16.5 Vertical Pod Autoscaler

Where HPA adds *more* pods, **VPA** makes *each* pod the right size by adjusting requests from observed usage. Run it in **`recommend`** mode to inform your manifests without surprise restarts.

```yaml
# repo/manifests/50-scaling/search-vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata: { name: search, namespace: tickethub }
spec:
  targetRef: { apiVersion: apps/v1, kind: Deployment, name: search }
  updatePolicy: { updateMode: "Off" }   # "Off" = recommend only (safe default)
```

!!! warning "Don't run HPA and VPA on the same metric"
    HPA-on-CPU and VPA-in-Auto-mode both reacting to CPU will fight each other. Safe
    combos: **HPA on CPU/custom + VPA in recommend-only**, or **VPA-Auto on memory + HPA
    on a custom metric**. Never both auto-adjusting the same resource.

### 16.6 KEDA — event-driven scaling

CPU is a poor signal for a queue consumer. **KEDA** scales **notifications** directly on **Kafka consumer lag** — and can scale to **zero** when idle.

```yaml
# repo/manifests/50-scaling/notifications-keda.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: notifications, namespace: tickethub }
spec:
  scaleTargetRef: { name: notifications }
  minReplicaCount: 0                     # scale to zero when no messages
  maxReplicaCount: 30
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-0.kafka.data:9092
        consumerGroup: notifications
        topic: ticket-events
        lagThreshold: "100"              # 1 replica per 100 messages of lag
```

### 16.7 Cluster Autoscaler — elastic nodes

HPA/KEDA can only place pods if there's room. When pods go **Pending** for lack of capacity, the **Cluster Autoscaler** provisions new worker VMs and drains/removes them when idle.

![Cluster autoscaler](assets/diagrams/16-cluster-autoscaler.png)

**The bare-metal caveat.** On a cloud, the autoscaler calls an API and a new node appears from an effectively infinite pool. On **Proxmox bare metal there is no infinite pool** — you can only autoscale within the physical RAM and cores you actually own. Making it work needs real plumbing: the **Cluster API Proxmox provider (CAPMOX)** clones new worker VMs from the golden template (Chapter 2), and the autoscaler is wired to that node group. Expect **minute-scale** provisioning (clone + boot + join + CNI ready), not the seconds a cloud gives you.

!!! warning "On bare metal, prefer standing headroom over just-in-time nodes"
    Because a bare-metal scale-up is slow and physically bounded, don't rely on it to
    absorb a sudden on-sale spike — the new node arrives *after* users have already seen
    errors. The pragmatic pattern: keep a **warm buffer** of spare capacity (a couple of
    idle nodes, or headroom pods via a low-priority "balloon" PriorityClass, Chapter 17)
    so HPA/KEDA can place pods **instantly**, and let the Cluster Autoscaler top the pool
    back up in the background. Autoscaling on bare metal manages *cost over hours*, not
    *bursts over seconds*.

!!! success "Chapter 16 checklist"
    - **Metrics Server** installed and verified (`kubectl top` works).
    - Stateless services have **HPA** on CPU/custom metrics with sane min/max + scale-down window.
    - **Custom-metric HPA** wired via **prometheus-adapter** (scale on rps/latency, not just CPU).
    - **VPA in recommend mode** informs request sizing; not fighting HPA on the same metric.
    - Queue consumers scaled by **KEDA** on lag (scale-to-zero where safe).
    - **Cluster Autoscaler** grows/shrinks the node pool so HPA/KEDA always have room.

---
