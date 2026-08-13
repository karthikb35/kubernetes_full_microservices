// TicketHub API Gateway — reverse proxy routing to backend microservices (Ch 12).
// Reads upstream URLs from env vars; falls back to localhost for local dev.
// Exposes /healthz and /readyz for Kubernetes probes (Ch 18).
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"time"
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// newProxy creates a reverse proxy to target, stripping the given prefix.
func newProxy(target, stripPrefix string) http.Handler {
	u, err := url.Parse(target)
	if err != nil {
		log.Fatalf("invalid upstream URL %q: %v", target, err)
	}
	rp := httputil.NewSingleHostReverseProxy(u)
	// Add X-Forwarded-For and preserve the original host.
	orig := rp.Director
	rp.Director = func(r *http.Request) {
		orig(r)
		r.Header.Set("X-Forwarded-Host", r.Host)
		r.Host = u.Host
	}
	if stripPrefix != "" {
		return http.StripPrefix(stripPrefix, rp)
	}
	return rp
}

func main() {
	ordersURL := getEnv("ORDERS_URL", "http://localhost:8081")
	catalogURL := getEnv("CATALOG_URL", "http://localhost:8082")

	mux := http.NewServeMux()

	// Kubernetes probes (Ch 18).
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})

	// Service info endpoint.
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{
			"service":   "gateway",
			"upstreams": "orders=" + ordersURL + " catalog=" + catalogURL,
		})
	})

	// Route /api/orders/* -> orders service.
	mux.Handle("/api/orders/", newProxy(ordersURL, ""))
	mux.Handle("/api/orders", newProxy(ordersURL, ""))

	// Route /api/catalog/* -> catalog service.
	mux.Handle("/api/catalog/", newProxy(catalogURL, ""))
	mux.Handle("/api/catalog", newProxy(catalogURL, ""))

	srv := &http.Server{
		Addr:         ":8080",
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
	}

	log.Printf("gateway listening on %s  orders=%s  catalog=%s", srv.Addr, ordersURL, catalogURL)
	log.Fatal(srv.ListenAndServe())
}
