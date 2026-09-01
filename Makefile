.PHONY: help build test lint pdf run-gateway run-orders run-frontend clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

build: ## Build Go services and the frontend
	cd repo/services/gateway && go build ./...
	cd repo/services/orders && go build ./...
	cd repo/services/frontend && npm ci && npm run build

test: ## Run Go unit tests and Python stub smoke tests
	cd repo/services/gateway && go test ./...
	cd repo/services/orders && go test ./...
	python -m unittest tests/smoke_services.py

lint: ## Validate Kubernetes manifests (requires kubeconform)
	kubeconform -summary -ignore-missing-schemas -ignore-filename-pattern prometheus-adapter-config.yaml -ignore-filename-pattern falco-rules.yaml repo/manifests/

pdf: ## Build the textbook PDF
	pip install -q markdown xhtml2pdf Pillow
	python build_pdf.py

html: ## Build the GitHub Pages static site (requires mkdocs-material)
	pip install -q mkdocs-material mkdocs-minify-plugin pymdown-extensions Pillow
	cp -r assets docs/
	mkdocs build


serve: ## Serve the site locally at http://127.0.0.1:8000
	pip install -q mkdocs-material mkdocs-minify-plugin pymdown-extensions Pillow
	cp -r assets docs/
	mkdocs serve

enrich: ## Add nuances / gotchas / architect sections to all doc chapters
	python enrich_docs.py

run-gateway: ## Run the gateway service locally (:8080)
	cd repo/services/gateway && go run ./cmd/gateway

run-orders: ## Run the orders service locally (:8080 API, :9090 metrics)
	cd repo/services/orders && go run ./cmd/orders

run-frontend: ## Run the frontend dev server (:3000)
	cd repo/services/frontend && npm install && npm run dev

clean: ## Remove build artifacts
	rm -f k8s-architecture.pdf
	rm -rf site/ docs/assets/
	rm -rf repo/services/frontend/dist repo/services/frontend/node_modules
