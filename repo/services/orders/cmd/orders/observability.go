// TicketHub Orders service — observability wiring (Ch 26).
//
// This file adds the two things the app must do so the platform can SEE it:
//   1. Expose Prometheus metrics (the RED series Chapter 26's alerts query).
//   2. Export OpenTelemetry trace spans to the collector -> Tempo.
//
// Illustrative: run `go mod tidy` to pull the exact indirect dependencies.
package main

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

// --- Metrics (RED method) ---------------------------------------------------
// These are the EXACT series Chapter 26's PrometheusRule alerts on:
//   http_requests_total{code=~"5.."}          -> Errors / Rate
//   http_request_duration_seconds_bucket      -> Duration (p99 via histogram)
var (
	httpRequests = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "Total HTTP requests by method, path and response code.",
		},
		[]string{"method", "path", "code"},
	)
	httpDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request latency in seconds.",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"method", "path"},
	)
)

// statusRecorder captures the status code so it can become a metric label.
type statusRecorder struct {
	http.ResponseWriter
	code int
}

func (r *statusRecorder) WriteHeader(c int) {
	r.code = c
	r.ResponseWriter.WriteHeader(c)
}

// metricsMiddleware records Rate, Errors and Duration for every request.
func metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, code: http.StatusOK}
		next.ServeHTTP(rec, r)
		httpRequests.WithLabelValues(r.Method, r.URL.Path, strconv.Itoa(rec.code)).Inc()
		httpDuration.WithLabelValues(r.Method, r.URL.Path).Observe(time.Since(start).Seconds())
	})
}

// --- Tracing (OpenTelemetry) ------------------------------------------------
// initTracer exports spans over OTLP to the collector, which forwards them to
// Tempo (Ch 26). Returns a shutdown func to flush spans on exit.
func initTracer(ctx context.Context, endpoint string) (func(context.Context) error, error) {
	exp, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint), // e.g. otel-collector.monitoring:4317
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp),
		sdktrace.WithResource(resource.NewWithAttributes(
			semconv.SchemaURL,
			semconv.ServiceName("orders"),
		)),
	)
	otel.SetTracerProvider(tp)
	return tp.Shutdown, nil
}
