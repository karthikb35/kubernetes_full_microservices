# ingress-tickethub.yaml — north-south HTTP entry point

> **Folder:** `10-platform` · **Chapter:** [Ch 7 — MetalLB & Ingress](../../../docs/07-metallb-ingress.md)

The single Ingress that terminates TLS and routes external traffic to the two
public-facing services. This is the front door for all browser and API traffic.

## Objects in this file

| Kind | Name | Namespace | Routing |
|---|---|---|---|
| Ingress | `tickethub` | `tickethub` | host `tickethub.example.com`, TLS secret `tickethub-tls` |

Paths: `/` → Service `frontend:80`, `/api` → Service `gateway:8080`.

## How it works

- The `cert-manager.io/cluster-issuer` annotation makes cert-manager provision
  the `tickethub-tls` Secret automatically.
- The ingress controller pulls a stable external IP from MetalLB, terminates
  HTTPS, and forwards to the backends by path.

## Relationships

![ingress routing](../../../assets/diagrams/mf-10-ingress-tickethub.png)

**Interacts with**
- [`cert-manager-issuers.yaml`](cert-manager-issuers.yaml) — supplies the TLS cert.
- [`metallb-pool.yaml`](metallb-pool.yaml) — supplies the external LoadBalancer IP.
- Services `frontend` and `gateway` — the routed backends (gateway is [`repo/services/gateway`](../../services/gateway)).

## Concept

![ingress flow](../../../assets/diagrams/07-ingress-flow.png)

See [Ch 7 — MetalLB & Ingress](../../../docs/07-metallb-ingress.md) for the full walkthrough.
