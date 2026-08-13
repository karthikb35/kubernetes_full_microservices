package main

import "testing"

func TestGetEnv(t *testing.T) {
	t.Setenv("GATEWAY_TEST_KEY", "from-env")
	if got := getEnv("GATEWAY_TEST_KEY", "fallback"); got != "from-env" {
		t.Fatalf("getEnv should return the env value, got %q", got)
	}
	if got := getEnv("GATEWAY_UNSET_KEY", "fallback"); got != "fallback" {
		t.Fatalf("getEnv should return the fallback, got %q", got)
	}
}

func TestNewProxyValidURL(t *testing.T) {
	// A valid upstream must not panic and must return a handler.
	if h := newProxy("http://localhost:8081", ""); h == nil {
		t.Fatal("newProxy returned nil for a valid URL")
	}
}
