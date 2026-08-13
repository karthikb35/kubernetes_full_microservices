module github.com/tickethub/orders

go 1.22

// Illustrative pins (Ch 26 instrumentation). Run `go mod tidy` to resolve the
// full indirect dependency set.
require (
	github.com/prometheus/client_golang v1.19.1
	go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp v0.52.0
	go.opentelemetry.io/otel v1.27.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.27.0
	go.opentelemetry.io/otel/sdk v1.27.0
)
