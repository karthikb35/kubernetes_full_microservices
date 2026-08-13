// TicketHub Orders service — minimal HTTP stub (Ch 10-12), now instrumented
// for observability (Ch 26). Real service would talk to Postgres + Kafka; this
// stub exposes the health/readiness endpoints the Kubernetes probes rely on
// (Ch 18), Prometheus metrics on :9090, and OpenTelemetry traces.
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

func main() {
	ctx := context.Background()

	// Tracing -> OTLP collector -> Tempo (Ch 26). Best-effort: don't crash the
	// service if the collector isn't reachable yet.
	if ep := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"); ep != "" {
		shutdown, err := initTracer(ctx, ep)
		if err != nil {
			log.Printf("tracing disabled: %v", err)
		} else {
			defer func() { _ = shutdown(ctx) }()
		}
	}

	app := http.NewServeMux()

	// Liveness: process is up.
	app.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	// Readiness: dependencies (DB, broker) are reachable.
	app.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})

	app.HandleFunc("/api/orders", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{
			"service": "orders",
			"status":  "stub",
		})
	})

	// Public router: wrap the app in an OpenTelemetry span + Prometheus RED
	// metrics for every request.
	instrumented := otelhttp.NewHandler(metricsMiddleware(app), "orders")

	// Metrics on a dedicated port so the ServiceMonitor's `port: metrics`
	// (Ch 26) scrapes /metrics without touching business traffic.
	go func() {
		m := http.NewServeMux()
		m.Handle("/metrics", promhttp.Handler())
		log.Printf("metrics listening on :9090/metrics")
		log.Fatal(http.ListenAndServe(":9090", m))
	}()

	addr := ":8080"
	log.Printf("orders listening on %s (payments=%s)", addr, os.Getenv("PAYMENTS_URL"))
	log.Fatal(http.ListenAndServe(addr, instrumented))
}
