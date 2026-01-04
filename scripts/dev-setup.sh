#!/bin/bash
set -e

echo "🚀 Setting up RAG Pipeline development environment..."

# Copy environment file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file from template"
else
    echo "ℹ️  .env file already exists, skipping"
fi

# Start infrastructure services first
echo "📦 Starting data stores..."
docker-compose up -d postgres qdrant opensearch redis minio

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if docker-compose ps | grep -q "(unhealthy)\|(starting)"; then
        echo "   Waiting for health checks... ($attempt/$max_attempts)"
        sleep 5
        attempt=$((attempt + 1))
    else
        break
    fi
done

if [ $attempt -eq $max_attempts ]; then
    echo "⚠️  Some services may not be healthy. Check with: docker-compose ps"
fi

# Initialize databases and indices
echo "🔧 Initializing databases..."

# Check if Python is available and run init scripts
if command -v python3 &> /dev/null; then
    echo "  Running Qdrant collection initialization..."
    python3 scripts/init-qdrant-collections.py 2>/dev/null || echo "  ⚠️  Qdrant init script failed or already initialized"
    
    echo "  Running OpenSearch index initialization..."
    python3 scripts/init-opensearch-index.py 2>/dev/null || echo "  ⚠️  OpenSearch init script failed or already initialized"
    
    echo "  Running MinIO bucket initialization..."
    python3 scripts/init-minio-buckets.py 2>/dev/null || echo "  ⚠️  MinIO init script failed or already initialized"
else
    echo "⚠️  Python3 not found. Skipping initialization scripts."
    echo "   You may need to run them manually:"
    echo "   - python scripts/init-qdrant-collections.py"
    echo "   - python scripts/init-opensearch-index.py"
    echo "   - python scripts/init-minio-buckets.py"
fi

echo ""
echo "✅ Infrastructure ready!"
echo ""
echo "To start all services (including app): docker-compose --profile app up -d"
echo "To start in background: docker-compose up -d"
echo ""
echo "Service URLs:"
echo "  - PostgreSQL:           localhost:5432"
echo "  - Qdrant:               http://localhost:6333"
echo "  - OpenSearch:           http://localhost:9200"
echo "  - OpenSearch Dashboards: http://localhost:5601"
echo "  - Redis:                localhost:6379"
echo "  - MinIO Console:        http://localhost:9001"
echo ""
echo "Application Services (use --profile app):"
echo "  - Ingestion API:        http://localhost:8001"
echo "  - Retrieval API:        http://localhost:8002"
echo "  - Orchestrator API:     http://localhost:8003"
echo "  - Embedding Service:    http://localhost:8080"
echo "  - LLM Gateway (Ollama): http://localhost:8004"
