# Suggested Commands

## Development Commands
```bash
# Set up development environment
make dev

# Start infrastructure services (postgres, redis, qdrant, opensearch, minio)
make up

# Start all services including app services
make up-all

# Stop all services
make down

# Follow logs
make logs

# Follow specific service logs
make logs-<service-name>

# Check service status
make status

# Check health endpoints
make health

# Run tests
make test

# Run linting
make lint

# Clean up environment and remove volumes
make clean
```

## Docker Compose
```bash
docker-compose up -d
docker-compose --profile app up -d
docker-compose --profile app down
docker-compose logs -f
docker-compose ps
```

## Kubernetes Commands
```bash
# Apply base resources
kubectl apply -k k8s/base

# Apply dev overlay
kubectl apply -k k8s/overlays/dev

# Apply prod overlay
kubectl apply -k k8s/overlays/prod

# Check deployments
kubectl get pods -n rag-pipeline
kubectl get services -n rag-pipeline
```

## System Commands (macOS/Darwin)
```bash
# Git
git status
git diff
git log --oneline

# File operations
ls -la
find . -name "*.py"
grep -r "pattern" .

# Process management
ps aux | grep python
```
