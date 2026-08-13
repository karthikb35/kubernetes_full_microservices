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

!!! success "Chapter 1 checklist — the architect's design outputs"
    - A **service catalog** with one clear responsibility per service.
    - A defined **interface/contract** for each (protocol + endpoints).
    - A **sync vs async** decision for every interaction.
    - **Database-per-service** ownership boundaries.
    - An **event flow** for the critical path (booking saga).

    With the *what* nailed down, Part I now turns to the *where* — the physical
    servers and VMs the cluster will run on.

---
