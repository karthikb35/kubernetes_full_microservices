package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// metricsMiddleware must record metrics without altering the downstream
// handler's status code.
func TestMetricsMiddlewarePassesThroughStatus(t *testing.T) {
	h := metricsMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/orders", nil))
	if rec.Code != http.StatusTeapot {
		t.Fatalf("expected status %d, got %d", http.StatusTeapot, rec.Code)
	}
}

// statusRecorder must capture the code written by the handler.
func TestStatusRecorderCapturesCode(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: httptest.NewRecorder(), code: http.StatusOK}
	rec.WriteHeader(http.StatusNotFound)
	if rec.code != http.StatusNotFound {
		t.Fatalf("expected recorded code %d, got %d", http.StatusNotFound, rec.code)
	}
}
