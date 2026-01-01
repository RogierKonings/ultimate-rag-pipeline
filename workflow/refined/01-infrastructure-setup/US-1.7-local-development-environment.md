# US-1.7: Local Development Environment

> **Epic:** Infrastructure Setup  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** None

## Objective

Create a complete Docker Compose setup that allows developers to run the entire RAG pipeline locally for development and testing.

## Architecture Reference

- All services from `docs/architecture.md` Service Architecture section
- Ports: PostgreSQL (5432), Qdrant (6333), OpenSearch (9200), Redis (6379), MinIO (9000)
- Services: Ingestion (8001), Retrieval (8002), Orchestrator (8003), LLM Gateway (8004)

## Implementation Tasks

### 1. Create Complete Docker Compose File

Create `docker-compose.yml`:

```yaml
version: "3.8"

services:
  # ============ DATA STORES ============
  postgres:
    image: postgres:16-alpine
    container_name: rag-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-raguser}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ragpass}
      POSTGRES_DB: ${POSTGRES_DB:-ragpipeline}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U raguser -d ragpipeline"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag-network

  qdrant:
    image: qdrant/qdrant:v1.7.4
    container_name: rag-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag-network

  opensearch:
    image: opensearchproject/opensearch:2.11.1
    container_name: rag-opensearch
    ports:
      - "9200:9200"
    environment:
      - cluster.name=rag-cluster
      - node.name=opensearch-node1
      - discovery.type=single-node
      - bootstrap.memory_lock=true
      - "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m"
      - DISABLE_INSTALL_DEMO_CONFIG=true
      - DISABLE_SECURITY_PLUGIN=true
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - opensearch_data:/usr/share/opensearch/data
    healthcheck:
      test: ["CMD-SHELL", "curl -s http://localhost:9200/_cluster/health | grep -q 'green\\|yellow'"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag-network

  redis:
    image: redis:7-alpine
    container_name: rag-redis
    ports:
      - "6379:6379"
    command: >
      redis-server
      --appendonly yes
      --maxmemory 256mb
      --maxmemory-policy allkeys-lru
      --requirepass ${REDIS_PASSWORD:-ragredis}
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-ragredis}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag-network

  minio:
    image: minio/minio:RELEASE.2024-01-01T16-36-33Z
    container_name: rag-minio
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-minioadmin123}
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - rag-network

  # ============ APPLICATION SERVICES ============
  ingestion-service:
    build:
      context: ./services/ingestion
      dockerfile: Dockerfile
    container_name: rag-ingestion
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql://raguser:ragpass@postgres:5432/ragpipeline
      - QDRANT_URL=http://qdrant:6333
      - OPENSEARCH_URL=http://opensearch:9200
      - REDIS_URL=redis://:ragredis@redis:6379
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin123}
      - EMBEDDING_SERVICE_URL=http://embedding-service:8080
      - LOG_LEVEL=DEBUG
    volumes:
      - ./services/ingestion:/app
      - ./services/shared:/app/shared
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      opensearch:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - rag-network

  ingestion-worker:
    build:
      context: ./services/ingestion
      dockerfile: Dockerfile
    container_name: rag-ingestion-worker
    command: celery -A tasks worker -l info -c 2
    environment:
      - DATABASE_URL=postgresql://raguser:ragpass@postgres:5432/ragpipeline
      - QDRANT_URL=http://qdrant:6333
      - OPENSEARCH_URL=http://opensearch:9200
      - REDIS_URL=redis://:ragredis@redis:6379
      - MINIO_ENDPOINT=minio:9000
      - EMBEDDING_SERVICE_URL=http://embedding-service:8080
    volumes:
      - ./services/ingestion:/app
      - ./services/shared:/app/shared
    depends_on:
      - redis
      - ingestion-service
    networks:
      - rag-network

  retrieval-service:
    build:
      context: ./services/retrieval
      dockerfile: Dockerfile
    container_name: rag-retrieval
    ports:
      - "8002:8002"
    environment:
      - DATABASE_URL=postgresql://raguser:ragpass@postgres:5432/ragpipeline
      - QDRANT_URL=http://qdrant:6333
      - OPENSEARCH_URL=http://opensearch:9200
      - REDIS_URL=redis://:ragredis@redis:6379
      - EMBEDDING_SERVICE_URL=http://embedding-service:8080
      - RERANKER_SERVICE_URL=http://reranker-service:8080
      - LOG_LEVEL=DEBUG
    volumes:
      - ./services/retrieval:/app
      - ./services/shared:/app/shared
    depends_on:
      - qdrant
      - opensearch
      - redis
    networks:
      - rag-network

  orchestrator-service:
    build:
      context: ./services/orchestrator
      dockerfile: Dockerfile
    container_name: rag-orchestrator
    ports:
      - "8003:8003"
    environment:
      - RETRIEVAL_SERVICE_URL=http://retrieval-service:8002
      - LLM_SERVICE_URL=http://llm-gateway:8004
      - REDIS_URL=redis://:ragredis@redis:6379
      - LOG_LEVEL=DEBUG
    volumes:
      - ./services/orchestrator:/app
      - ./services/shared:/app/shared
    depends_on:
      - retrieval-service
      - redis
    networks:
      - rag-network

  # ============ ML SERVICES (CPU versions for local dev) ============
  embedding-service:
    build:
      context: ./services/embedding
      dockerfile: Dockerfile.cpu
    container_name: rag-embedding
    ports:
      - "8080:8080"
    environment:
      - MODEL_NAME=BAAI/bge-large-en-v1.5
      - MAX_BATCH_SIZE=32
    volumes:
      - model_cache:/root/.cache/huggingface
    networks:
      - rag-network

  # For local dev without GPU, use Ollama or mock
  llm-gateway:
    image: ollama/ollama:latest
    container_name: rag-ollama
    ports:
      - "8004:11434"
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - rag-network

volumes:
  postgres_data:
  qdrant_data:
  opensearch_data:
  redis_data:
  minio_data:
  model_cache:
  ollama_data:

networks:
  rag-network:
    driver: bridge
```

### 2. Create Environment Template

Create `.env.example`:

```bash
# PostgreSQL
POSTGRES_USER=raguser
POSTGRES_PASSWORD=ragpass
POSTGRES_DB=ragpipeline

# Redis
REDIS_PASSWORD=ragredis

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123

# Embedding Model
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
EMBEDDING_DIM=1024

# LLM (for production)
LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct

# Application
LOG_LEVEL=DEBUG
ENVIRONMENT=development
```

### 3. Create Service Dockerfiles

Create `services/ingestion/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Add shared modules to path
ENV PYTHONPATH=/app:/app/shared

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
```

### 4. Create Development Scripts

Create `scripts/dev-setup.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Setting up RAG Pipeline development environment..."

# Copy environment file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file from template"
fi

# Start infrastructure services first
echo "📦 Starting data stores..."
docker-compose up -d postgres qdrant opensearch redis minio

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Initialize databases and indices
echo "🔧 Initializing databases..."
python scripts/init-postgres.py
python scripts/init-qdrant-collections.py
python scripts/init-opensearch-index.py
python scripts/init-minio-buckets.py

echo "✅ Infrastructure ready!"
echo ""
echo "To start all services: docker-compose up"
echo "To start in background: docker-compose up -d"
echo ""
echo "Service URLs:"
echo "  - Ingestion API: http://localhost:8001"
echo "  - Retrieval API: http://localhost:8002"
echo "  - Orchestrator API: http://localhost:8003"
echo "  - MinIO Console: http://localhost:9001"
echo "  - OpenSearch: http://localhost:9200"
```

Create `scripts/dev-teardown.sh`:

```bash
#!/bin/bash
echo "🧹 Tearing down RAG Pipeline environment..."

docker-compose down -v

echo "✅ Environment stopped and volumes removed"
```

Create `scripts/dev-logs.sh`:

```bash
#!/bin/bash
# Follow logs for a specific service or all services
SERVICE=${1:-""}

if [ -z "$SERVICE" ]; then
    docker-compose logs -f
else
    docker-compose logs -f "$SERVICE"
fi
```

### 5. Create Hot-Reload Configuration

Create `services/ingestion/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
select = ["E", "F", "I"]

[tool.mypy]
python_version = "3.11"
strict = true
```

### 6. Create Makefile for Common Commands

Create `Makefile`:

```makefile
.PHONY: help dev up down logs test lint

help:
	@echo "RAG Pipeline Development Commands"
	@echo ""
	@echo "  make dev      - Set up development environment"
	@echo "  make up       - Start all services"
	@echo "  make down     - Stop all services"
	@echo "  make logs     - Follow all logs"
	@echo "  make test     - Run all tests"
	@echo "  make lint     - Run linting"

dev:
	./scripts/dev-setup.sh

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

test:
	docker-compose exec ingestion-service pytest
	docker-compose exec retrieval-service pytest
	docker-compose exec orchestrator-service pytest

lint:
	docker-compose exec ingestion-service ruff check .
	docker-compose exec retrieval-service ruff check .
	docker-compose exec orchestrator-service ruff check .

clean:
	./scripts/dev-teardown.sh
```

## Acceptance Criteria

- [ ] `docker-compose.yml` with all services defined
- [ ] All data stores (PostgreSQL, Qdrant, OpenSearch, Redis, MinIO) configured
- [ ] Service placeholders for ingestion, retrieval, orchestrator
- [ ] Volume mounts for code hot-reload
- [ ] Environment variable templates in `.env.example`
- [ ] Development scripts (setup, teardown, logs)
- [ ] Makefile with common commands
- [ ] Health checks for all services
- [ ] Network configuration for inter-service communication

## Verification Commands

```bash
# Setup environment
make dev

# Start all services
make up

# Check service status
docker-compose ps

# Check logs
make logs

# Test health endpoints
curl http://localhost:6333/health  # Qdrant
curl http://localhost:9200/_cluster/health  # OpenSearch
curl http://localhost:9000/minio/health/live  # MinIO

# Stop everything
make down
```

## Files to Create

1. `docker-compose.yml`
2. `.env.example`
3. `services/ingestion/Dockerfile`
4. `services/retrieval/Dockerfile`
5. `services/orchestrator/Dockerfile`
6. `services/embedding/Dockerfile.cpu`
7. `scripts/dev-setup.sh`
8. `scripts/dev-teardown.sh`
9. `scripts/dev-logs.sh`
10. `Makefile`
