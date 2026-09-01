## <a name="ch1"></a>1. The TicketHub Scenario — Services, Interfaces & Interactions

Before we rack a single server, an architect must understand **what we are building and why**. Infrastructure exists to serve an application, so we design the application's shape first, then let it drive every cluster decision that follows.

### 1.1 The business scenario

**TicketHub** is an online platform where **event organizers** publish events (concerts, sports, theatre) and **end users** browse, hold seats, pay, and receive tickets. It must handle spiky traffic — when a popular event goes on sale, thousands of users hit "buy" in the same minute — which makes it a perfect case study for **autoscaling, resilience, and stateful data** on Kubernetes.

![TicketHub system context](assets/diagrams/01-context.png)

The platform lives in an **on-prem data center** (our Kubernetes cluster) and talks to two **external providers**: a payment gateway (Stripe) and an email/SMS provider (SendGrid).

!!! mental "Mental model — the cluster is a city, services are shops"
    Think of the cluster as a **city**. The **API Gateway** is the city gate (everyone
    enters through it). Each **microservice** is a specialized shop with its own staff
    and its own storeroom (**database-per-service**). Some interactions are a
    face-to-face conversation (**synchronous** REST/gRPC), others are dropping a
    letter in the mail that gets processed later (**asynchronous** events via Kafka).

### 1.2 The service catalog

TicketHub is decomposed into **9 microservices**, each with a single responsibility, its own API, and its own data. This is the heart of the architecture:

![TicketHub microservices and data plane](assets/diagrams/01-microservices.png)

| # | Service | Responsibility | Stateless? | Backing store | Scaling driver |
|---|---------|----------------|------------|---------------|----------------|
| 1 | **Frontend UI** | Server-rendered web app (Next.js) | Yes | — | Web traffic (HPA on CPU) |
| 2 | **API Gateway** | Single entry point: authN, routing, rate-limiting | Yes | — | Request rate |
| 3 | **Users / Auth** | Accounts, login, JWT issuance | Yes | PostgreSQL `users_db` | Login rate |
| 4 | **Catalog** | Events, venues, seat maps (read-heavy) | Yes | PostgreSQL `catalog_db` | Read QPS |
| 5 | **Inventory** | Seat availability & short-lived **holds** | Yes* | Redis (holds) + PostgreSQL | Hold rate (spiky) |
| 6 | **Orders** | Booking lifecycle & saga orchestration | Yes | PostgreSQL `orders_db` | Order rate |
| 7 | **Payments** | Stripe integration, capture/refund | Yes | PostgreSQL `payments_db` | Order rate |
| 8 | **Notifications** | Email/SMS on events (async consumer) | Yes | Redis (dedupe) | Kafka lag (**KEDA**) |
| 9 | **Search** | Event discovery / indexing | Yes | Object store + index | Query rate |

Plus the **stateful data plane** (runs *inside* the cluster as StatefulSets in Part III): **PostgreSQL**, **Redis**, **Kafka**, and **Rook-Ceph** object storage.

!!! note "Why 'stateless' services still have databases"
    A service is **stateless** when the *pod* holds no durable data — any replica can
    serve any request, and losing a pod loses nothing. The durable state lives in the
    **database**, not the pod. That's what lets us scale Orders from 3 to 30 replicas
    freely. Truly **stateful** components (Postgres, Kafka) get special treatment
    (StatefulSets, stable identity, persistent volumes) in Chapter 11 and 14.

### 1.3 Interfaces each service exposes

An architect defines **contracts**, not implementations. Each service exposes a narrow, versioned interface:

| Service | Protocol | Key endpoints / interface | Consumed by |
|---------|----------|---------------------------|-------------|
| API Gateway | HTTPS (REST) | `/*` → routes to services; verifies JWT | Internet (via Ingress) |
| Users/Auth | REST + gRPC | `POST /login`, `POST /register`, `GET /verify` | Gateway, all services (token verify) |
| Catalog | REST + gRPC | `GET /events`, `GET /events/{id}`, `GET /venues/{id}` | Gateway, Search |
| Inventory | gRPC | `HoldSeats()`, `ReleaseSeats()`, `ConfirmSeats()` | Orders |
| Orders | REST | `POST /orders`, `GET /orders/{id}` | Gateway |
| Payments | gRPC | `Authorize()`, `Capture()`, `Refund()` | Orders |
| Notifications | Kafka consumer | subscribes `orders.*`, `payments.*` | (event-driven) |
| Search | REST | `GET /search?q=` | Gateway |

!!! note "REST, gRPC and JWT in one breath"
    **REST** is resource-oriented HTTP/JSON — simple and browser-friendly, so TicketHub
    speaks it at the **edge**. **gRPC** is a fast, strongly-typed binary protocol over
    HTTP/2, better for high-volume **internal** service-to-service calls. A **JWT** (JSON
    Web Token) is a signed token the Users/Auth service issues at login; the gateway
    verifies it on every request to prove who the caller is. All three are in the table
    above — see the Glossary (Appendix A) for one-line refreshers.

!!! tip "gRPC internally, REST at the edge"
    A common architect pattern: expose **REST/JSON at the edge** (browser-friendly,
    via the Gateway) but use **gRPC between internal services** (faster, strongly
    typed, streaming). Kubernetes `ClusterIP` services and Cilium handle both
    equally — we'll wire this up in Chapter 12.

### 1.4 Synchronous vs asynchronous interactions

Not every interaction should be a blocking call. Choosing sync vs async per interaction is one of the most important design decisions:

![Synchronous vs asynchronous interactions](assets/diagrams/01-sync-async.png)

- **Synchronous (REST/gRPC)** — the caller waits for an answer. Use when the user needs an **immediate result**: "is this seat available?", "did my payment succeed?".
- **Asynchronous (Kafka events)** — the caller emits an event and moves on. Use for **side-effects and fan-out**: sending a confirmation email, updating the search index, analytics. If Notifications is briefly down, orders still succeed and emails flush when it recovers — **decoupling for resilience**.

### 1.5 A booking, end to end

Here's how the services collaborate for the core "buy a ticket" flow — a mix of synchronous calls (for the transaction) and an asynchronous event (for the receipt):

![Booking sequence](assets/diagrams/01-booking-sequence.png)

This flow also illustrates the **Saga pattern**: Orders orchestrates a multi-step transaction across Inventory and Payments. If payment fails, Orders issues a compensating `ReleaseSeats()` — because there are no distributed ACID transactions across microservices.

!!! note "What the Saga pattern is (and why we need it)"
    A single database gives **ACID** guarantees — a multi-step change either fully commits
    or fully rolls back. Across *separate* service databases (Inventory, Payments, Orders)
    there is **no** shared transaction, so a crash mid-way could leave seats held but
    unpaid. A **Saga** replaces the one big transaction with a *sequence of local commits*,
    each paired with a **compensating** undo. Orders runs the saga — hold seats, charge,
    confirm — and if the charge fails it fires `ReleaseSeats()` to compensate. You trade a
    distributed lock for explicit undo steps and eventual consistency.

### 1.6 Database-per-service

Notice each service owns its **own** database and never reaches into another's:

![Database per service](assets/diagrams/01-db-per-service.png)

!!! key "Architect's rule — own your data"
    A service's database is **private**. No other service connects to it directly.
    Others get that data only through the owning service's **API** or through
    **events**. This is what allows each service to scale, evolve its schema, and
    fail **independently** — the entire promise of microservices. Violating it
    (a shared database) recreates a distributed monolith, the worst of both worlds.

### 1.7 What this means for the cluster (foreshadowing)

Every application decision above creates an infrastructure requirement we'll fulfil in later chapters:

| Application need | Cluster capability | Chapter |
|------------------|--------------------|---------|
| Spiky on-sale traffic | HPA + KEDA + Cluster Autoscaler | 16 |
| Stateful Postgres/Kafka | StatefulSets + Rook-Ceph PVs | 11, 14 |
| Service-to-service calls | ClusterIP + Cilium + NetworkPolicy | 12, 21 |
| Isolation between teams/services | Namespaces + RBAC + ResourceQuota | 9, 15, 19 |
| Secure payments | Secrets, PSA, Falco, image signing | 20, 23, 24 |
| Zero-downtime releases | Rolling updates, PDB, Argo CD | 18, 28 |


### 1.8 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - A "stateless" service pod can still hold **in-flight request state** (goroutine/thread memory) — pod loss during a request causes a 5xx to the client. This is unavoidable without client-side retry logic or a service mesh retry policy.
    - The Kafka `OrderConfirmed` event is **at-least-once** delivered. Notifications must check a Redis dedup key before sending an email to prevent duplicate receipts — a subtle invariant that often gets dropped when the Notifications service is rewritten.
    - The 10-minute seat-hold TTL must be enforced in three places consistently: Redis key TTL, application-level expiry check on the Orders write path, AND the UI countdown timer. Any mismatch causes ghost holds (seats held but expired) or double-booking (hold released while user still on checkout page).

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Shared database anti-pattern**: connecting Orders directly to `users_db` to avoid an RPC call seems harmless but creates a hidden schema coupling. Resist it — it is the most common path back to a distributed monolith.
    - **Synchronous saga orchestration** means Orders holds a DB transaction open while waiting for Inventory and Payments RPCs. Slow external calls (Stripe latency spikes) translate directly to Postgres connection exhaustion. Timeout every external RPC and compensate explicitly.
    - **Missing idempotency keys on payment capture**: if the Orders pod restarts mid-saga after `Authorize()` but before writing the result, it may call `Authorize()` again on retry — resulting in a double-charge. Every payment RPC must carry a stable idempotency key derived from the `orderId`.

!!! question "Architect Considerations"
    1. **Thundering-herd on sale open**: 50,000 users hit the Inventory service in the same second. Is Redis `SETNX` for holds safe under this load, or do you need a distributed queue (Redis Streams, Kafka) to serialize the seat-hold requests?
    2. **Stripe outage strategy**: should failed payment attempts be queued in Kafka and retried asynchronously (better UX for users), or returned as 402 immediately (simpler, but worse conversion)?
    3. **Eventual consistency visibility**: when a seat is held by User A, how quickly does the event page for User B show it as unavailable? A 10-second lag is acceptable for concerts; a 1-second lag is acceptable for limited edition sneakers. Define the SLO before building.
    4. **Decomposition boundary review**: is a separate Payments service justified for TicketHub, or should Orders own payment capture? The boundary matters because it determines who handles Stripe webhook callbacks.
    5. **Event schema versioning**: `OrderConfirmed` v1 carries `{ orderId, userId, seats[] }`. When you add `promoCode` in v2, Notifications (consuming v1) must not break. Plan Avro/Protobuf schema registry or envelope versioning from the start.
    6. **Capacity model**: a single sold-out stadium event generates ~60,000 concurrent users over 5 minutes. Work backwards to per-service RPS, then to pod count, then to node count — this is the exercise that determines your HPA max replicas in Chapter 16.

!!! success "Chapter 1 checklist — the architect's design outputs"
    - A **service catalog** with one clear responsibility per service.
    - A defined **interface/contract** for each (protocol + endpoints).
    - A **sync vs async** decision for every interaction.
    - **Database-per-service** ownership boundaries.
    - An **event flow** for the critical path (booking saga).

    With the *what* nailed down, Part I now turns to the *where* — the physical
    servers and VMs the cluster will run on.

---
