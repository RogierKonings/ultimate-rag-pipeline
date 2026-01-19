# Developer CLI Tools

This directory contains CLI tools for common development operations in the RAG pipeline.

## Quick Start

```bash
# Install dependencies (if not using Docker)
pip install httpx rich

# Check service health
python scripts/dev-health.py

# Run a test query
python scripts/dev-query.py "What is RAG?"

# Ingest a document
python scripts/dev-ingest.py file document.pdf

# Trigger index reconciliation (dry run)
python scripts/dev-reconcile.py --tenant dev-tenant --dry-run
```

## Available Tools

| Tool | Description |
|------|-------------|
| `dev-health.py` | Check health of all RAG pipeline services |
| `dev-query.py` | Test RAG queries with debug output |
| `dev-ingest.py` | Ingest documents via CLI |
| `dev-reconcile.py` | Trigger index reconciliation |

---

## dev-health.py

Check health of all RAG pipeline services.

### Usage

```bash
# Basic health check
python scripts/dev-health.py

# JSON output (for scripting)
python scripts/dev-health.py --json

# Continuous monitoring
python scripts/dev-health.py --watch --interval 5
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Output in JSON format |
| `--watch` | Continuously monitor health |
| `--interval N` | Watch interval in seconds (default: 5) |

### Services Checked

- Ingestion Service (`:8001`)
- Retrieval Service (`:8002`)
- Orchestrator Service (`:8003`)
- Embedding Service (`:8080`)
- Qdrant (`:6333`)
- OpenSearch (`:9200`)
- Redis (`:6379`)
- PostgreSQL (`:5432`)
- MinIO (`:9000`)

### Exit Codes

- `0`: All services healthy
- `1`: One or more services unhealthy

---

## dev-query.py

Test RAG queries against the orchestrator service with optional debug output.

### Usage

```bash
# Simple query
python scripts/dev-query.py "What is RAG?"

# With debug output
python scripts/dev-query.py "How does chunking work?" --debug

# Custom tenant and top-k
python scripts/dev-query.py "Explain embeddings" --tenant my-tenant --top-k 5

# Adjust semantic vs keyword weight
python scripts/dev-query.py "Find authentication docs" --semantic-weight 0.5

# JSON output
python scripts/dev-query.py "What is RAG?" --json
```

### Options

| Option | Description |
|--------|-------------|
| `--tenant ID` | Tenant ID (default: `dev-tenant`) |
| `--top-k N` | Number of results to retrieve (default: 10) |
| `--debug` | Enable debug output with timing and retrieval info |
| `--stream` | Stream response using SSE |
| `--semantic-weight N` | Semantic vs keyword weight 0-1 (default: 0.7) |
| `--json` | Output in JSON format |

### Debug Output

When using `--debug`, the tool displays:
- **Timing breakdown**: Latency for each component (embedding, search, reranking, LLM)
- **Retrieval info**: Strategy used, result counts at each stage
- **Token usage**: Prompt and completion token counts
- **Intent classification**: How the query was classified

---

## dev-ingest.py

CLI tool for document ingestion operations.

### Usage

```bash
# Ingest a local file
python scripts/dev-ingest.py file document.pdf

# Ingest from URL
python scripts/dev-ingest.py url https://example.com/doc.pdf

# Wait for completion
python scripts/dev-ingest.py file document.pdf --wait

# Use semantic chunking
python scripts/dev-ingest.py file document.pdf --chunking semantic

# Check job status
python scripts/dev-ingest.py status <job-id>

# List ingested documents
python scripts/dev-ingest.py list --tenant my-tenant

# Delete a document
python scripts/dev-ingest.py delete <document-id>
```

### Commands

| Command | Description |
|---------|-------------|
| `file <path>` | Ingest a local file |
| `url <url>` | Ingest from a URL |
| `status <job-id>` | Check ingestion job status |
| `list` | List ingested documents |
| `delete <doc-id>` | Delete a document |

### Options (file/url commands)

| Option | Description |
|--------|-------------|
| `--tenant ID` | Tenant ID (default: `dev-tenant`) |
| `--chunking STRATEGY` | Chunking strategy: `recursive`, `semantic`, `hierarchical` |
| `--wait` | Wait for job completion |
| `--json` | Output in JSON format |

### Options (list command)

| Option | Description |
|--------|-------------|
| `--tenant ID` | Tenant ID (default: `dev-tenant`) |
| `--limit N` | Number of documents (default: 20) |
| `--offset N` | Offset for pagination |

---

## dev-reconcile.py

Trigger index reconciliation between PostgreSQL and external stores (Qdrant, OpenSearch).

### Usage

```bash
# Dry run (report issues without fixing)
python scripts/dev-reconcile.py --tenant dev-tenant --dry-run

# Actually fix issues
python scripts/dev-reconcile.py --tenant dev-tenant --no-dry-run

# Reconcile specific document
python scripts/dev-reconcile.py --tenant dev-tenant --document <doc-id>

# Check job status
python scripts/dev-reconcile.py status <job-id>

# Wait for completion
python scripts/dev-reconcile.py --tenant dev-tenant --wait
```

### Options

| Option | Description |
|--------|-------------|
| `--tenant ID` | Tenant ID to reconcile (required) |
| `--document ID` | Specific document ID (optional) |
| `--dry-run` | Report issues without fixing (default) |
| `--no-dry-run` | Actually repair issues |
| `--wait` | Wait for job completion |
| `--token TOKEN` | JWT token for authentication |
| `--json` | Output in JSON format |

### Reconciliation Process

1. **Find missing chunks**: Chunks in PostgreSQL but not in Qdrant/OpenSearch
2. **Find orphaned entries**: Entries in Qdrant/OpenSearch without PostgreSQL record
3. **Repair**: Re-index missing chunks, remove orphaned entries

> **Note**: Requires admin privileges. Provide a JWT token with admin role using `--token`.

---

## Other Scripts

### Infrastructure Scripts

| Script | Description |
|--------|-------------|
| `dev-setup.sh` | Set up development environment |
| `dev-teardown.sh` | Tear down development environment |
| `dev-logs.sh` | View service logs |

### Initialization Scripts

| Script | Description |
|--------|-------------|
| `init-minio-buckets.py` | Create MinIO buckets |
| `init-opensearch-index.py` | Create OpenSearch indices |
| `init-qdrant-collections.py` | Create Qdrant collections |
| `init-ollama-models.sh` | Pull Ollama models |

### Security Scripts

| Script | Description |
|--------|-------------|
| `generate-jwt-keys.sh` | Generate JWT signing keys |
| `security-scan.sh` | Run security scans |
| `export-audit-logs.py` | Export audit logs |
| `generate_security_report.py` | Generate security report |

### Backup Scripts

| Script | Description |
|--------|-------------|
| `postgres-backup.sh` | Backup PostgreSQL database |

---

## Configuration

The CLI tools read service URLs from environment variables, with sensible defaults for local development.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_SERVICE_URL` | `http://localhost:8001` | Ingestion service URL |
| `RETRIEVAL_SERVICE_URL` | `http://localhost:8002` | Retrieval service URL |
| `ORCHESTRATOR_SERVICE_URL` | `http://localhost:8003` | Orchestrator service URL |
| `EMBEDDING_SERVICE_URL` | `http://localhost:8080` | Embedding service URL |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost:6333` | Qdrant connection |
| `OPENSEARCH_HOST` / `OPENSEARCH_PORT` | `localhost:9200` | OpenSearch connection |
| `REDIS_HOST` / `REDIS_PORT` | `localhost:6379` | Redis connection |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost:5432` | PostgreSQL connection |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |

You can also use host/port pairs (e.g., `INGESTION_HOST` + `INGESTION_PORT`) instead of full URLs.

### Example: Remote Services

```bash
export ORCHESTRATOR_SERVICE_URL=http://rag-orchestrator.example.com:8003
python scripts/dev-query.py "What is RAG?"
```

---

## Requirements

The CLI tools require:
- Python 3.11+
- `httpx` - HTTP client
- `rich` (optional) - Enhanced terminal output

Install with:
```bash
pip install httpx rich
```

Or if using the project's virtual environment:
```bash
pip install -r requirements-dev.txt
```

---

## Troubleshooting

### Connection Refused

If you see "Connection refused" errors:
1. Ensure services are running: `make status`
2. Start services: `make up-all`
3. Check logs: `make logs`

### Authentication Errors

For admin operations (like reconciliation):
1. Generate a JWT token with admin role
2. Pass it with `--token <token>`

### Rich Not Available

The tools work without `rich` but with plain text output:
```bash
pip install rich
```
