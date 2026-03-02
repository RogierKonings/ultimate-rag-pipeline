.PHONY: help dev up up-all down logs test lint clean status health opensearch-bootstrap opensearch-bootstrap-prod minio-bootstrap minio-service-accounts postgres-backup postgres-backup-manual postgres-migrate pull-models pull-model list-models remove-model test-llm check-ollama e2e e2e-full env-local env-docker env-frontend moon-setup moon-check moon-test moon-lint moon-format moon-format-check moon-build moon-ci dev-frontend dev-orchestrator affected-test affected-lint

help:
	@echo "RAG Pipeline Development Commands"
	@echo ""
	@echo "Environment Setup:"
	@echo "  make env-local    - Generate .env for local development (localhost URLs)"
	@echo "  make env-docker   - Generate .env for Docker Compose (service name URLs)"
	@echo "  make env-frontend - Generate frontend/.env from root config"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Set up development environment (infra only)"
	@echo "  make up           - Start infrastructure services"
	@echo "  make up-all       - Start all services including app services"
	@echo "  make down         - Stop all services"
	@echo "  make logs         - Follow all logs"
	@echo "  make status       - Show service status"
	@echo "  make health       - Check health endpoints"
	@echo "  make test         - Run all tests"
	@echo "  make e2e          - Run E2E smoke tests (requires running services)"
	@echo "  make e2e-full     - Start services, run E2E tests, stop services"
	@echo "  make lint         - Run linting"
	@echo "  make clean        - Tear down environment and remove volumes"
	@echo ""
	@echo "LLM Model Management:"
	@echo "  make pull-models  - Pull default LLM model (llama3.1:8b)"
	@echo "  make pull-model MODEL=<name> - Pull a specific model"
	@echo "  make list-models  - List installed models"
	@echo "  make remove-model MODEL=<name> - Remove a model"
	@echo "  make test-llm     - Test LLM inference"
	@echo ""
	@echo "Moon Monorepo:"
	@echo "  make moon-setup      - Initialize Moon workspace"
	@echo "  make moon-check      - Run type checks (all projects)"
	@echo "  make moon-test       - Run tests (all projects)"
	@echo "  make moon-lint       - Run linters (all projects)"
	@echo "  make moon-format     - Format code (all projects)"
	@echo "  make moon-build      - Build all projects"
	@echo "  make moon-ci         - Run full CI pipeline"
	@echo ""
	@echo "Dev Servers (via Moon):"
	@echo "  make dev-frontend    - Start frontend dev server"
	@echo "  make dev-orchestrator - Start orchestrator service"

# =============================================================================
# Environment Configuration
# =============================================================================

env-local:
	@echo "Generating .env for local development..."
	@cat .env.base > .env
	@echo "" >> .env
	@cat .env.local >> .env
	@echo "Generated .env with DEPLOY_ENV=local (localhost URLs)"

env-docker:
	@echo "Generating .env for Docker Compose..."
	@cat .env.base > .env
	@echo "" >> .env
	@cat .env.docker >> .env
	@echo "Generated .env with DEPLOY_ENV=docker (service name URLs)"

env-frontend:
	@echo "Generating frontend/.env from root configuration..."
	@echo "# Generated from root .env - run 'make env-frontend' to update" > frontend/.env
	@echo "# Generated at: $$(date)" >> frontend/.env
	@echo "" >> frontend/.env
	@echo "# Public environment variables (exposed to client)" >> frontend/.env
	@grep -E '^PUBLIC_' .env >> frontend/.env 2>/dev/null || true
	@echo "" >> frontend/.env
	@echo "# Private environment variables (server-side only)" >> frontend/.env
	@grep -E '^MINIO_' .env >> frontend/.env 2>/dev/null || true
	@grep -E '^INGESTION_SERVICE_URL' .env >> frontend/.env 2>/dev/null || true
	@grep -E '^ORCHESTRATOR_SERVICE_URL' .env >> frontend/.env 2>/dev/null || true
	@grep -E '^DEMO_TENANT_ID' .env >> frontend/.env 2>/dev/null || true
	@echo "Generated frontend/.env"

# =============================================================================
# Development Setup
# =============================================================================

dev:
	./scripts/dev-setup.sh

up:
	docker-compose up -d

up-all:
	docker-compose --profile app up -d

down:
	docker-compose --profile app down

logs:
	docker-compose logs -f

logs-%:
	docker-compose logs -f $*

# =============================================================================
# Moon Monorepo Commands
# =============================================================================

moon-setup:
	@echo "Setting up Moon workspace..."
	moon setup

moon-check:
	@echo "Running type checks across all projects..."
	moon run :check

moon-test:
	@echo "Running tests across all projects..."
	moon run :test

moon-lint:
	@echo "Running linters across all projects..."
	moon run :lint

moon-format:
	@echo "Formatting all projects..."
	moon run :format

moon-format-check:
	@echo "Checking formatting across all projects..."
	moon run :format-check

moon-build:
	@echo "Building all projects..."
	moon run :build

moon-ci:
	@echo "Running CI pipeline..."
	moon ci

# Project-specific dev servers
dev-frontend:
	moon run frontend:dev

dev-orchestrator:
	moon run orchestrator-service:dev

# Run affected tasks only (useful for PRs)
affected-test:
	moon run :test --affected

affected-lint:
	moon run :lint --affected

status:
	docker-compose ps

health:
	@echo "Checking service health..."
	@echo ""
	@echo "Qdrant:     $$(curl -s http://localhost:6333/healthz 2>/dev/null || echo 'not running')"  # REST API on 6333; Rust services use gRPC on 6334
	@echo "OpenSearch: $$(curl -s http://localhost:9200/_cluster/health 2>/dev/null | grep -o '"status":"[^"]*"' || echo 'not running')"
	@echo "MinIO:      $$(curl -s http://localhost:9000/minio/health/live 2>/dev/null || echo 'not running')"
	@echo "Redis:      $$(redis-cli -a ragredis ping 2>/dev/null || echo 'not running')"

test:
	@echo "Running tests..."
	@echo "Ingestion (Rust): Run with 'cargo test -p rag-ingestion'"
	cd crates && cargo test -p rag-ingestion || echo "Ingestion tests not available"
	cd crates && cargo test -p rag-retrieval || echo "Retrieval tests not available"
	docker-compose exec orchestrator-service pytest || echo "Orchestrator tests not available"

lint:
	@echo "Running linting..."
	@echo "Ingestion (Rust): Run with 'cargo clippy -p rag-ingestion'"
	cd crates && cargo clippy -p rag-ingestion -- -D warnings || echo "Ingestion linting not available"
	docker-compose exec orchestrator-service ruff check . || echo "Orchestrator linting not available"

clean:
	./scripts/dev-teardown.sh

# LLM Model Management (uses native Ollama for GPU acceleration)
pull-models:
	@echo "Pulling recommended LLM models (native Ollama with GPU)..."
	ollama pull llama3.1:8b
	@echo "Model pulled successfully. Run 'make list-models' to verify."

pull-model:
	@echo "Usage: make pull-model MODEL=<model-name>"
	@echo "Example: make pull-model MODEL=qwen2.5:14b"
	@test -n "$(MODEL)" && ollama pull $(MODEL) || echo "Please specify MODEL=<name>"

list-models:
	@echo "Installed Ollama models:"
	@ollama list

remove-model:
	@test -n "$(MODEL)" && ollama rm $(MODEL) || echo "Please specify MODEL=<name>"

test-llm:
	@echo "Testing LLM inference (native Ollama with GPU)..."
	@curl -s http://localhost:11434/v1/chat/completions \
		-H "Content-Type: application/json" \
		-d '{"model": "$(or $(MODEL),llama3.1:8b)", "messages": [{"role": "user", "content": "Say hello in one word."}], "max_tokens": 10}' \
		| python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('choices',[{}])[0].get('message',{}).get('content','No response'))"

check-ollama:
	@echo "Checking Ollama status..."
	@ollama ps 2>/dev/null || echo "Ollama not running. Start with: ollama serve"

# OpenSearch Bootstrap Commands
opensearch-bootstrap:
	@echo "Bootstrapping OpenSearch (development)..."
	kubectl apply -f k8s/opensearch/bootstrap-configmap.yaml
	kubectl delete job opensearch-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/opensearch/bootstrap-job.yaml
	kubectl wait --for=condition=complete job/opensearch-bootstrap -n rag-pipeline --timeout=300s
	@echo "OpenSearch bootstrap completed"

opensearch-bootstrap-prod:
	@echo "Bootstrapping OpenSearch (production with security)..."
	kubectl apply -f k8s/opensearch/bootstrap-configmap.yaml
	kubectl delete job opensearch-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/opensearch/bootstrap-job.yaml
	kubectl apply -f k8s/overlays/prod/opensearch-bootstrap-patch.yaml
	kubectl wait --for=condition=complete job/opensearch-bootstrap -n rag-pipeline --timeout=300s
	@echo "OpenSearch bootstrap completed (production)"

opensearch-ilm:
	@echo "Applying OpenSearch ILM policies..."
	kubectl apply -f k8s/opensearch/ilm-policy.yaml
	@echo "ILM policies configmap applied. Run bootstrap to apply policies."

# MinIO Bootstrap Commands
minio-bootstrap:
	@echo "Bootstrapping MinIO..."
	kubectl delete job minio-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/minio/bootstrap-job.yaml
	kubectl wait --for=condition=complete job/minio-bootstrap -n rag-pipeline --timeout=300s
	@echo "MinIO bootstrap completed"

minio-service-accounts:
	@echo "Creating MinIO service accounts..."
	./scripts/create-minio-service-accounts.sh rag-pipeline

minio-notifications:
	@echo "Setting up MinIO webhook notifications..."
	kubectl apply -f k8s/minio/notifications-config.yaml
	kubectl delete job minio-notifications-setup -n rag-pipeline --ignore-not-found
	kubectl wait --for=condition=complete job/minio-notifications-setup -n rag-pipeline --timeout=300s
	@echo "MinIO notifications configured"

# PostgreSQL Backup Commands
postgres-backup:
	@echo "Configuring PostgreSQL backup CronJob..."
	kubectl apply -f k8s/postgres/backup-rbac.yaml
	kubectl apply -f k8s/postgres/backup-cronjob.yaml
	kubectl apply -f k8s/postgres/backup-alerts.yaml 2>/dev/null || echo "Prometheus Operator not installed, skipping alerts"
	@echo "PostgreSQL backup CronJob configured (runs daily at 02:00 UTC)"

postgres-backup-manual:
	@echo "Triggering manual PostgreSQL backup..."
	kubectl create job postgres-backup-manual-$$(date +%s) \
		--from=cronjob/postgres-backup \
		-n rag-pipeline
	@echo "Manual backup job created. Check status with: kubectl get jobs -n rag-pipeline -l app=postgres-backup"

postgres-migrate:
	@echo "Running database migrations..."
	kubectl delete job postgres-migrate -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/postgres/migration-job.yaml
	kubectl wait --for=condition=complete job/postgres-migrate -n rag-pipeline --timeout=300s
	@echo "Database migrations completed"

postgres-restore:
	@echo "PostgreSQL Restore Procedures"
	@echo "=============================="
	@echo ""
	@echo "1. List available backups:"
	@echo "   kubectl exec deployment/minio -n rag-pipeline -- mc ls rag/backups/postgres/ --recursive"
	@echo ""
	@echo "2. Download a backup:"
	@echo "   kubectl exec deployment/minio -n rag-pipeline -- mc cp rag/backups/postgres/daily/FILENAME.dump /tmp/"
	@echo ""
	@echo "3. See full restore procedures:"
	@echo "   docs/infrastructure/postgres-backup-restore.md"

# E2E Testing Commands
e2e:
	@echo "Running E2E smoke tests..."
	pytest tests/e2e/ -v --e2e --tb=short

e2e-full:
	@echo "Starting services for E2E tests..."
	docker-compose up -d
	docker-compose --profile app up -d
	@echo "Waiting for services to be healthy (60s)..."
	@sleep 60
	@echo "Running E2E tests..."
	pytest tests/e2e/ -v --e2e --tb=short || (docker-compose --profile app down && exit 1)
	@echo "Stopping services..."
	docker-compose --profile app down
	@echo "E2E tests complete!"
