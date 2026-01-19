# Testing Documentation

> **User Story**: US-10.6.1 - End-to-End Smoke Test Suite
> **Priority**: P2
> **Status**: Done

This section documents the testing infrastructure for the RAG pipeline, including unit tests, integration tests, and end-to-end smoke tests.

## Overview

The RAG pipeline implements a comprehensive testing strategy:

| Test Type | Location | Purpose | Run Command |
|-----------|----------|---------|-------------|
| Unit Tests | `services/*/tests/` | Test individual components | `pytest services/*/tests/` |
| Integration Tests | `tests/integration/` | Test service interactions | `pytest tests/integration/` |
| E2E Smoke Tests | `tests/e2e/` | Validate full pipeline | `pytest tests/e2e/ --e2e` |

## E2E Smoke Tests

End-to-end smoke tests validate the entire pipeline from ingestion through retrieval to generation.

### Test Coverage

The E2E test suite (`tests/e2e/test_rag_pipeline.py`) covers:

1. **Health Checks**: Verify all services are healthy
2. **Query Response**: Validate response structure and content
3. **Latency Bounds**: Assert query latency < 5 seconds (E2E target)
4. **Citations**: Verify citations are returned when requested
5. **Streaming**: Test SSE streaming responses
6. **Error Handling**: Validate graceful handling of invalid inputs
7. **Concurrency**: Test multiple simultaneous queries

### Canonical Test Dataset

The test suite uses 10 documents with known answers covering:

- Python programming
- Machine learning
- Cloud computing
- Database technologies
- Web development
- Security best practices
- DevOps principles
- API design
- Data structures
- Computer networking

Each document has associated queries with expected substrings to validate response accuracy.

### Running E2E Tests

#### Prerequisites

1. All services running (`make up-all`)
2. Ollama with `llama3.1:8b` model (or configured LLM)
3. Python 3.11+ with test dependencies

#### Local Execution

```bash
# Start all services
make up-all

# Wait for services to be healthy
python scripts/dev-health.py --watch

# Run E2E tests
pytest tests/e2e/ -v --e2e

# Run specific test
pytest tests/e2e/test_rag_pipeline.py::TestRagPipelineE2E::test_query_returns_response -v --e2e
```

#### Using Docker Compose

```bash
# Run E2E tests in container
docker-compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yaml \
  --profile e2e run --rm e2e-tests
```

### CI Integration

E2E tests run automatically via GitHub Actions (`.github/workflows/e2e-tests.yml`):

- **Trigger**: Push to `main`, pull requests, weekly schedule
- **Timeout**: 30 minutes
- **Services**: Full stack started via docker-compose

```yaml
# Example workflow usage
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sundays
```

### Configuration

E2E tests are configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_URL` | `http://localhost:8001` | Ingestion service URL |
| `ORCHESTRATOR_URL` | `http://localhost:8003` | Orchestrator service URL |
| `RETRIEVAL_URL` | `http://localhost:8002` | Retrieval service URL |
| `E2E_TENANT_ID` | `00000000-...` | Test tenant UUID |
| `E2E_INGESTION_TIMEOUT` | `60` | Ingestion timeout (seconds) |
| `E2E_QUERY_TIMEOUT` | `30` | Query timeout (seconds) |
| `E2E_POLL_INTERVAL` | `2` | Job polling interval (seconds) |

### Test Structure

```
tests/e2e/
├── conftest.py              # Fixtures and configuration
├── test_rag_pipeline.py     # Main E2E test suite
├── test_video_rag_pipeline.py # Video RAG tests
├── docker-compose.e2e.yaml  # E2E test orchestration
└── Dockerfile               # E2E test runner image
```

### Fixtures

Key fixtures provided by `conftest.py`:

- `e2e_config`: Configuration object with service URLs and timeouts
- `http_client`: Async HTTP client (httpx)
- `auth_headers`: Authentication headers for API requests

### Latency Targets

| Test | Target | Notes |
|------|--------|-------|
| Query response | < 5s | Full RAG cycle |
| Concurrent queries (5x) | < 30s total | Parallelism validation |
| Streaming TTFT | < 1s | First token |

### Troubleshooting

#### Tests Skipped

If tests are skipped with "need --e2e option":

```bash
pytest tests/e2e/ -v --e2e  # Add --e2e flag
```

#### Service Not Available

```bash
# Check service health
python scripts/dev-health.py

# Start services
make up-all

# Check logs
make logs-orchestrator
```

#### Timeout Errors

Increase timeouts for slow environments:

```bash
E2E_QUERY_TIMEOUT=60 pytest tests/e2e/ -v --e2e
```

## Integration Test Patterns

For integration testing patterns and guidelines, see [Integration Test Patterns](../integration-test-patterns.md).

## See Also

- [Developer CLI Tools](../developer-cli-tools.md) - CLI tools for debugging
- [Health Check Specification](../health-check-specification.md) - Health endpoint contracts
- [Integration Test Patterns](../integration-test-patterns.md) - Testing guidelines
