# End-to-End (E2E) Testing Guide

This guide explains how to run the E2E smoke tests that validate the full RAG pipeline.

## Prerequisites

1. **Docker & Docker Compose** - For running infrastructure
2. **Ollama** - Running locally with `llama3.1:8b` model for LLM inference
3. **Python 3.11+** (for local runs only)

## Quick Start

### Running E2E Tests Locally

```bash
# 1. Start infrastructure + app services
make up-all

# 2. Wait for services to be healthy
make health

# 3. Run E2E tests
make e2e

# 4. Cleanup when done
make down
```

### Running Full E2E Suite (Start → Test → Stop)

```bash
make e2e-full
```

## Test Coverage

The E2E smoke tests validate:

| Test | Description |
|------|-------------|
| `test_health_endpoints` | All services respond to health checks |
| `test_query_returns_response` | Orchestrator returns valid response |
| `test_query_latency_within_bounds` | E2E latency < 5 seconds |
| `test_citations_in_response` | Citations included when requested |
| `test_streaming_query` | SSE streaming works |
| `test_invalid_query_handling` | API validates input properly |
| `test_concurrent_queries` | System handles 5 concurrent requests |

## Canonical Test Dataset

The tests use 10 documents with known Q&A pairs covering:
- Python, Machine Learning, Cloud Computing
- Databases, Web Development, Security
- DevOps, API Design, Data Structures, Networking

## Running in CI

The E2E tests run automatically:
- On push to `main`
- On PRs to `main` 
- Weekly (Sunday 00:00 UTC)

See `.github/workflows/e2e-tests.yml` for CI configuration.

## Running with Docker

```bash
# Start services and run E2E tests in a container
docker-compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yaml \
  --profile app --profile e2e up

# Or run tests against already-running services
docker-compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yaml \
  --profile e2e run e2e-tests
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_URL` | `http://localhost:8001` | Ingestion service URL |
| `ORCHESTRATOR_URL` | `http://localhost:8003` | Orchestrator service URL |
| `RETRIEVAL_URL` | `http://localhost:8002` | Retrieval service URL |
| `E2E_TENANT_ID` | Demo tenant UUID | Tenant ID for tests |
| `E2E_QUERY_TIMEOUT` | `30` | Query timeout in seconds |

## Troubleshooting

### Tests skip with "Ingestion service not available"

Services aren't running. Start them with:
```bash
make up-all
```

### "Ollama not running"

The orchestrator needs Ollama for LLM inference:
```bash
ollama serve  # Start Ollama
ollama pull llama3.1:8b  # Pull required model
```

### Queries timeout

Check orchestrator logs for LLM issues:
```bash
docker-compose logs orchestrator-service
```

## Writing New E2E Tests

1. Add tests to `tests/e2e/test_rag_pipeline.py`
2. Use the `@pytest.mark.e2e` marker
3. Use the `http_client` and `e2e_config` fixtures
4. Add expected Q&A pairs to `TEST_DOCUMENTS` if testing specific answers
