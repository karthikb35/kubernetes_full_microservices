# TicketHub Orders service — multi-stage, distroless, non-root (Ch 10).
# ---- Stage 1: build ----
FROM golang:1.22 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/orders ./cmd/orders

# ---- Stage 2: runtime ----
FROM gcr.io/distroless/static:nonroot
COPY --from=builder /out/orders /orders
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/orders"]
