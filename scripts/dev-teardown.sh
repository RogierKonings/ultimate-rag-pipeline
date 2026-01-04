#!/bin/bash

echo "🧹 Tearing down RAG Pipeline environment..."

# Stop all services and remove volumes
docker-compose --profile app down -v

echo "✅ Environment stopped and volumes removed"
echo ""
echo "To keep data volumes, use: docker-compose down"
