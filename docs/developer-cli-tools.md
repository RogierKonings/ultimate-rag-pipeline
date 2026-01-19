# Developer CLI Tools Guide

> **User Story**: US-10.6.3 - Developer CLI Tools
> **Priority**: P2
> **Effort**: Small (1-2 days)

This guide documents the CLI tools available for debugging and testing the RAG pipeline during development.

## Overview

The RAG pipeline includes four CLI tools to streamline common development operations:

| Tool | Purpose | Port |
|------|---------|------|
| `dev-health.py` | Check all service health endpoints | Multiple |
| `dev-query.py` | Test RAG queries with debug output | 8003 |
| `dev-ingest.py` | Ingest documents via CLI | 8001 |
| `dev-reconcile.py` | Trigger index reconciliation | 8001 |

## Installation

The tools are located in the `scripts/` directory and require Python 3.11+ with:

```bash
pip install httpx rich
```

For enhanced terminal output, install `rich`:
```bash
pip install rich
```

## Health Check Tool

Check the health of all RAG pipeline services with a single command.

### Basic Usage

```bash
python scripts/dev-health.py
```

Output:
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃         RAG Pipeline Service Health                 ┃
┣━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┫
┃ Service      ┃ Status       ┃ Details  ┃ Latency    ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━┩
│ Ingestion    │ ● Healthy    │ OK       │ 12ms       │
│ Retrieval    │ ● Healthy    │ OK       │ 8ms        │
│ Orchestrator │ ● Healthy    │ OK       │ 15ms       │
│ Embedding    │ ● Healthy    │ OK       │ 5ms        │
│ Qdrant       │ ● Healthy    │ OK       │ 3ms        │
│ OpenSearch   │ ● Healthy    │ green    │ 25ms       │
│ Redis        │ ● Healthy    │ TCP OK   │ -          │
│ PostgreSQL   │ ● Healthy    │ TCP OK   │ -          │
│ MinIO        │ ● Healthy    │ OK       │ 10ms       │
└──────────────┴──────────────┴──────────┴────────────┘
```

### Continuous Monitoring

Monitor service health continuously:

```bash
python scripts/dev-health.py --watch --interval 5
```

### JSON Output

For scripting and CI/CD pipelines:

```bash
python scripts/dev-health.py --json
```

```json
{
  "timestamp": "2024-01-15T10:30:00.000000",
  "services": [...],
  "summary": {
    "total": 9,
    "healthy": 9,
    "degraded": 0,
    "unhealthy": 0
  }
}
```

### Exit Codes

- `0`: All services healthy
- `1`: One or more services unhealthy (useful for CI checks)

## Query Tool

Test RAG queries with detailed debug output.

### Basic Query

```bash
python scripts/dev-query.py "What is RAG?"
```

### Debug Mode

Enable debug output to see timing, retrieval stats, and more:

```bash
python scripts/dev-query.py "How does chunking work?" --debug
```

Output includes:
- Response with citations
- Timing breakdown per component
- Retrieval statistics (semantic/keyword counts, fusion, reranking)
- Token usage

### Query Options

```bash
# Custom tenant
python scripts/dev-query.py "query" --tenant my-tenant

# Limit results
python scripts/dev-query.py "query" --top-k 5

# Adjust hybrid search weights (0 = all keyword, 1 = all semantic)
python scripts/dev-query.py "query" --semantic-weight 0.5

# Stream response (SSE)
python scripts/dev-query.py "query" --stream
```

### Debugging Retrieval Issues

Use the debug output to diagnose retrieval quality:

1. **Low semantic results**: Check embedding quality or data coverage
2. **Low keyword results**: Check OpenSearch indexing
3. **High pre-rerank, low post-rerank**: Reranker is filtering effectively
4. **High latency on embedding**: Model service may be overloaded

## Ingestion Tool

Ingest documents into the RAG pipeline.

### Ingest a File

```bash
python scripts/dev-ingest.py file document.pdf
```

### Ingest with Options

```bash
# Specify tenant
python scripts/dev-ingest.py file document.pdf --tenant my-tenant

# Use semantic chunking
python scripts/dev-ingest.py file document.pdf --chunking semantic

# Wait for completion with progress
python scripts/dev-ingest.py file document.pdf --wait
```

### Ingest from URL

```bash
python scripts/dev-ingest.py url https://example.com/document.pdf
```

### Check Job Status

```bash
python scripts/dev-ingest.py status <job-id>
```

### List Documents

```bash
python scripts/dev-ingest.py list --tenant dev-tenant
```

### Delete Document

```bash
python scripts/dev-ingest.py delete <document-id>
```

## Reconciliation Tool

Trigger index reconciliation to fix inconsistencies between PostgreSQL and external stores.

### Dry Run (Default)

Check for issues without making changes:

```bash
python scripts/dev-reconcile.py --tenant dev-tenant --dry-run
```

### Fix Issues

Actually repair inconsistencies:

```bash
python scripts/dev-reconcile.py --tenant dev-tenant --no-dry-run
```

### Reconcile Specific Document

```bash
python scripts/dev-reconcile.py --tenant dev-tenant --document <doc-id>
```

### Wait for Completion

```bash
python scripts/dev-reconcile.py --tenant dev-tenant --wait
```

### Authentication

Reconciliation requires admin privileges:

```bash
python scripts/dev-reconcile.py --tenant dev-tenant --token <jwt-token>
```

## Common Workflows

### 1. Debug a Failing Query

```bash
# Check services are healthy
python scripts/dev-health.py

# Run query with debug
python scripts/dev-query.py "my failing query" --debug

# Check retrieval at different weights
python scripts/dev-query.py "my query" --debug --semantic-weight 0.3
python scripts/dev-query.py "my query" --debug --semantic-weight 0.9
```

### 2. Test Document Ingestion

```bash
# Ingest and wait
python scripts/dev-ingest.py file test.pdf --wait

# Verify with a query
python scripts/dev-query.py "content from test.pdf" --debug

# Check document appears in list
python scripts/dev-ingest.py list
```

### 3. Diagnose Index Issues

```bash
# Run reconciliation dry run
python scripts/dev-reconcile.py --tenant dev-tenant --dry-run --wait

# If issues found, fix them
python scripts/dev-reconcile.py --tenant dev-tenant --no-dry-run --wait
```

### 4. CI/CD Health Checks

```bash
#!/bin/bash
# In your CI pipeline

# Wait for services to start
sleep 30

# Check health (exits 1 if unhealthy)
python scripts/dev-health.py --json > health.json
if [ $? -ne 0 ]; then
    echo "Services unhealthy!"
    cat health.json
    exit 1
fi
```

## Troubleshooting

### Connection Refused

```
Error: Could not connect to service at http://localhost:8003
```

**Solution**: Ensure services are running:
```bash
make status
make up-all
```

### HTTP 403 Forbidden (Reconciliation)

```
Error: Admin privileges required
```

**Solution**: Provide a JWT token with admin role:
```bash
python scripts/dev-reconcile.py --tenant dev-tenant --token <admin-jwt>
```

### No Rich Output

If you see plain text instead of formatted tables:
```bash
pip install rich
```

### Timeout Errors

For large documents or slow networks, increase timeout:
```bash
# Edit the script or set environment variable
export HTTP_TIMEOUT=120
```

## Integration with Make

These tools complement the existing Makefile commands:

```bash
# Start services
make up-all

# Check health (uses dev-health.py internally if available)
make health

# View logs for debugging
make logs
make logs-orchestrator
```

## See Also

- [Architecture Documentation](architecture.md)
- [Ingestion Service](ingestion-service/README.md)
- [Retrieval Service](retrieval-service/README.md)
- [Orchestrator Service](orchestrator-service/README.md)
- [Health Check Specification](health-check-specification.md)
