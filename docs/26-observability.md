## <a name="ch26"></a>26. Observability — Prometheus, Grafana, Loki & Hubble

TicketHub is now built, scaled, and secured — but if you can't **see** what it's doing, you're flying blind. When a concert on-sale spikes and checkout slows, you need to know *within seconds* whether it's CPU, the database, a bad deploy, or a network policy. **Observability** turns a running cluster into a system you can reason about.

### 26.1 The three pillars

![Three pillars](assets/diagrams/26-three-pillars.png)

| Pillar | Tool | Answers |
|--------|------|---------|
| **Metrics** | Prometheus | *Is* something wrong? (numeric trends) |
| **Logs** | Loki | *What* happened? (events) |
| **Traces** | Tempo / Hubble | *Where* did the time go? (request path) |

**Grafana** unifies all three over the same time window — one pane of glass.

!!! mental "Mental model — a hospital patient monitor"
    **Metrics** are the **vital signs** — heart rate, blood pressure, trending on a screen;
    an alarm fires when they leave range. **Logs** are the **nurse's notes** — discrete
    events describing what occurred. **Traces** are the **X-ray** showing exactly where the
    blockage is. You need all three: vitals tell you there's a problem, notes and imaging
    tell you what and where.

### 26.2 Metrics with Prometheus

Prometheus **pulls** a `/metrics` endpoint from every target on an interval, stores time-series in its TSDB, evaluates alert rules, and hands data to Grafana and Alertmanager.

![Prometheus](assets/diagrams/26-prometheus.png)

Deployed via the **kube-prometheus-stack** Helm chart, which brings Prometheus, Alertmanager, Grafana, `node-exporter` (Chapter 11 DaemonSet), and `kube-state-metrics`. Services expose metrics and are discovered by a **ServiceMonitor**:

```yaml
# repo/manifests/70-observability/orders-monitoring.yaml (ServiceMonitor section)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: orders
  namespace: tickethub
  labels: { release: kube-prometheus-stack }
spec:
  selector:
    matchLabels: { app: orders }
  endpoints:
    - port: metrics          # scrape orders' /metrics
      interval: 15s
```

A **PrometheusRule** turns metrics into alerts — this one uses the RED method (Rate, Errors, Duration):

```yaml
# repo/manifests/70-observability/orders-monitoring.yaml (PrometheusRule section)
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata: { name: tickethub-slo, namespace: tickethub }
spec:
  groups:
    - name: tickethub.rules
      rules:
        - alert: OrdersHighErrorRate
          expr: |
            sum(rate(http_requests_total{app="orders",code=~"5.."}[5m]))
              / sum(rate(http_requests_total{app="orders"}[5m])) > 0.02
          for: 5m
          labels: { severity: page }
          annotations:
            summary: "Orders 5xx error rate above 2% for 5m"
```

!!! key "Alert on symptoms (SLOs), not causes"
    Page humans on **user-facing symptoms** — high error rate, high latency, checkout
    failures — not on every high-CPU blip. CPU can be 90% and users perfectly happy;
    that's a scaling signal (HPA, Chapter 16), not a 2am page. The **RED** (Rate/Errors/
    Duration) and **USE** (Utilization/Saturation/Errors) methods keep alerts meaningful.

### 26.3 Instrumenting a service — where the telemetry comes from

The alert above queries `http_requests_total` and `http_request_duration_seconds` — but Prometheus doesn't invent those series. **The application produces them.** A ServiceMonitor with nothing to scrape is just a scheduled 404. This section closes the loop: how the `orders` service actually emits metrics and traces.

**Metrics — the Prometheus client library.** You register two series (a **counter** for request volume/errors, a **histogram** for latency), increment them in a middleware, and expose `/metrics`:

```go
// repo/services/orders/cmd/orders/observability.go
var (
    httpRequests = promauto.NewCounterVec(
        prometheus.CounterOpts{Name: "http_requests_total"},
        []string{"method", "path", "code"},            // the labels the alert filters on
    )
    httpDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "http_request_duration_seconds",
            Buckets: prometheus.DefBuckets,             // -> _bucket series for p99
        },
        []string{"method", "path"},
    )
)

func metricsMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        rec := &statusRecorder{ResponseWriter: w, code: 200}
        next.ServeHTTP(rec, r)
        httpRequests.WithLabelValues(r.Method, r.URL.Path, strconv.Itoa(rec.code)).Inc()
        httpDuration.WithLabelValues(r.Method, r.URL.Path).Observe(time.Since(start).Seconds())
    })
}
```

The counter's `code` label is exactly what `code=~"5.."` matches; the histogram is what `histogram_quantile(0.99, ...)` reads. **Name your metrics to match your alerts, or the alerts are fiction.** The service exposes `/metrics` on a dedicated port `9090`, and the Deployment's Service names that port `metrics` — which is what the ServiceMonitor's `port: metrics` resolves to.

![Instrumentation pipeline](assets/diagrams/26-instrumentation.png)

**Traces — OpenTelemetry.** Metrics tell you *orders is slow*; a **trace** tells you *the slow part was the 380 ms Postgres call, not the app*. You initialize an OTLP exporter once, then wrap the router so every request becomes a **span**:

```go
// Export spans over OTLP to the collector -> Tempo.
exp, _ := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpoint(endpoint))
tp := sdktrace.NewTracerProvider(
    sdktrace.WithBatcher(exp),
    sdktrace.WithResource(resource.NewWithAttributes(
        semconv.SchemaURL, semconv.ServiceName("orders"))),
)
otel.SetTracerProvider(tp)

// One line wraps every handler in a span and propagates context downstream.
instrumented := otelhttp.NewHandler(metricsMiddleware(app), "orders")
```

The magic is **context propagation**: `otelhttp` injects a `traceparent` header on outbound calls, so when `orders` calls `payments`, both spans share one **trace ID**. Grafana stitches them into a single waterfall. The spans flow `app -> OTLP -> OpenTelemetry Collector -> Tempo`, deployed in `repo/manifests/70-observability/otel-collector-tempo.yaml`.

**Logs — just write structured JSON to stdout.** No library ceremony: emit one JSON object per line to stdout and let Loki's agent (next section) collect it. Include the `trace_id` so a log line links straight to its trace:

```go
log.Printf(`{"level":"error","msg":"payment declined","order_id":%q,"trace_id":%q}`,
    orderID, traceIDFromContext(r.Context()))
```

!!! key "Instrument once, correlate everywhere"
    The payoff of shared conventions: the **same** `app` and `path` labels appear on
    metrics, the **same** `trace_id` appears on logs and spans, and Grafana pivots between
    all three over one time window. A spiking `http_requests_total{code="500"}` -> click to
    the Loki lines with that `trace_id` -> click to the Tempo waterfall showing the failed
    Postgres span. Three pillars, one incident, ten seconds.

### 26.4 Logs with Loki

Loki is "Prometheus for logs" — a per-node agent (**Promtail/Alloy**, a DaemonSet) tails container stdout/stderr, **labels** each line (namespace, pod, app), and ships it. Loki indexes only the **labels** (cheap), not full text.

![Logging](assets/diagrams/26-logging.png)

```logql
# LogQL — find orders errors during the incident window
{namespace="tickethub", app="orders"} |= "error" | json | status >= 500
```

Because Loki and Prometheus share the **same labels**, you jump from a spiking metric to the exact logs in one click in Grafana.

### 26.5 Network observability with Hubble

Chapter 6 installed **Hubble** on top of Cilium. It's the "trace" pillar for the network — the live service map, and which flows were **allowed or dropped** by the NetworkPolicies from Chapter 21:

```bash
hubble observe --namespace tickethub --verdict DROPPED   # see what policy blocked
```

!!! warning "Store observability data on durable, separate storage"
    Prometheus and Loki hold your incident-response history — put them on **Ceph-backed
    PVs** (Chapter 8) in the `monitoring` namespace, sized for real retention, and back
    them up (Chapter 27). Metrics/logs on ephemeral `emptyDir` vanish exactly when a node
    dies — the moment you most need to look back. Keep them off the nodes they observe.

!!! success "Chapter 26 checklist"
    - **kube-prometheus-stack** running; services expose `/metrics` via **ServiceMonitors**.
    - Alerts defined on **SLO symptoms** (RED/USE), routed by Alertmanager to Slack/PagerDuty.
    - **Loki + Promtail** shipping labeled logs; correlate with metrics by shared labels.
    - **Hubble** for network flow visibility (allowed/dropped).
    - Observability data on **durable Ceph storage** with retention, not `emptyDir`.

---
