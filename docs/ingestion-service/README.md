# Ingestion Service Documentation

The Ingestion Service is responsible for document intake, processing, and indexing in the RAG pipeline. It handles the complete workflow from source acquisition to vector storage.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Source Connectors](#source-connectors)
- [Document Parsers](#document-parsers)
- [Chunking Engine](#chunking-engine)
- [Embedding Service](#embedding-service)
- [Index Writers](#index-writers)
- [Metadata Enrichment](#metadata-enrichment)
- [Async Processing](#async-processing)
- [API Reference](#api-reference)
- [Configuration](#configuration)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Ingestion Service                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   Source     │   │   Document   │   │   Chunking   │   │   Embedding  │  │
│  │  Connectors  │──▶│   Parsers    │──▶│    Engine    │──▶│   Service    │  │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘  │
│         │                                                         │          │
│         │                                                         ▼          │
│         │                                              ┌──────────────────┐  │
│         │                                              │  Index Writers   │  │
│         │                                              │  ┌────────────┐  │  │
│         ▼                                              │  │   Qdrant   │  │  │
│  ┌──────────────┐                                      │  ├────────────┤  │  │
│  │   Metadata   │                                      │  │ OpenSearch │  │  │
│  │  Enrichment  │─────────────────────────────────────▶│  ├────────────┤  │  │
│  └──────────────┘                                      │  │ PostgreSQL │  │  │
│                                                        │  └────────────┘  │  │
│                                                        └──────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     Celery Task Queue (Redis)                          │  │
│  │  Queues: ingestion | embedding | reembed | dlq                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
services/ingestion/
├── api/
│   ├── routes/
│   │   ├── documents.py      # Document CRUD operations
│   │   ├── ingest.py         # Ingestion endpoints (sync/reembed)
│   │   └── migrations.py     # Embedding migration endpoints
│   ├── schemas/
│   │   ├── documents.py      # Document request/response schemas
│   │   ├── ingest.py         # Ingestion schemas
│   │   └── migrations.py     # Migration schemas
│   ├── dependencies.py       # FastAPI dependency injection
│   └── middleware.py         # Authentication, logging middleware
├── connectors/
│   ├── base.py               # BaseConnector ABC
│   ├── filesystem.py         # Local/S3 file connector
│   ├── database.py           # PostgreSQL/MySQL connector
│   ├── web.py                # Web crawler connector
│   └── api.py                # REST API connector
├── processors/
│   ├── parsers/
│   │   ├── base.py           # BaseParser ABC
│   │   ├── pdf.py            # PDF parsing (PyMuPDF)
│   │   ├── docx.py           # Word document parsing
│   │   ├── html.py           # HTML/web page parsing
│   │   ├── markdown.py       # Markdown parsing
│   │   ├── text.py           # Plain text parsing
│   │   └── registry.py       # Parser auto-detection registry
│   ├── chunking.py           # Chunking strategies (784 lines)
│   └── enrichment/
│       ├── enrichment.py     # Enrichment orchestrator
│       ├── language_detector.py
│       ├── pii_detector.py   # Presidio-based PII detection
│       ├── metadata_extractor.py
│       └── models.py         # Enrichment data models
├── embedding/
│   ├── service.py            # EmbeddingService main class
│   ├── client.py             # Model client abstraction
│   ├── cache.py              # Redis embedding cache
│   └── models.py             # Embedding data models
├── indexing/
│   ├── base.py               # BaseIndexWriter ABC
│   ├── qdrant.py             # Qdrant vector writer
│   ├── opensearch.py         # OpenSearch keyword writer
│   ├── postgres.py           # PostgreSQL metadata writer
│   └── coordinator.py        # Multi-store index coordinator
├── migrations/
│   ├── embedding_migrator.py # Zero-downtime model migration
│   ├── collection_manager.py # Qdrant collection aliasing
│   └── progress_tracker.py   # Migration progress tracking
├── tasks/
│   ├── celery_app.py         # Celery configuration
│   ├── ingest.py             # Ingestion task definitions
│   ├── reembed.py            # Re-embedding tasks
│   ├── status.py             # Job status management
│   └── callbacks.py          # Task lifecycle callbacks
├── services/
│   └── documents.py          # Document service layer
├── config.py                 # Settings with validation
├── telemetry.py              # OpenTelemetry + Prometheus
├── run.py                    # Application entry point
└── worker.py                 # Celery worker entry
```

---

## Source Connectors

Four production-ready connectors for acquiring documents from various sources.

### Filesystem Connector

```python
from ingestion.connectors.filesystem import FilesystemConnector

connector = FilesystemConnector(
    source_type="filesystem",
    config={
        "path": "/data/documents",
        "recursive": True,
        "include_patterns": ["*.pdf", "*.docx"],
        "exclude_patterns": ["*draft*", "*temp*"]
    }
)

# List available documents
documents = await connector.list_documents()

# Fetch specific document
doc = await connector.fetch("report.pdf")
```

**Features:**
- Local filesystem and S3/MinIO support
- Recursive directory traversal
- Glob pattern filtering (include/exclude)
- Automatic MIME type detection
- Metadata extraction (size, modified date)

### Database Connector

```python
from ingestion.connectors.database import DatabaseConnector

connector = DatabaseConnector(
    source_type="database",
    config={
        "type": "postgresql",  # or "mysql"
        "connection_string": "postgresql://user:pass@host:5432/db",
        "query": "SELECT id, title, content FROM documents WHERE updated_at > :since",
        "id_column": "id",
        "content_column": "content"
    }
)
```

**Features:**
- PostgreSQL and MySQL support
- Custom SQL queries with parameterization
- Incremental sync via timestamp columns
- Connection pooling with asyncpg/aiomysql
- Batch fetching for large result sets

### Web Connector

```python
from ingestion.connectors.web import WebConnector

connector = WebConnector(
    source_type="web",
    config={
        "start_urls": ["https://docs.example.com"],
        "max_depth": 3,
        "max_pages": 100,
        "allowed_domains": ["docs.example.com"],
        "respect_robots_txt": True,
        "rate_limit": 1.0  # requests per second
    }
)
```

**Features:**
- Configurable crawl depth and page limits
- Domain restriction and robots.txt compliance
- Rate limiting to avoid overloading servers
- URL deduplication
- JavaScript rendering support (optional)

### API Connector

```python
from ingestion.connectors.api import APIConnector

connector = APIConnector(
    source_type="api",
    config={
        "base_url": "https://api.example.com",
        "endpoints": ["/documents", "/articles"],
        "auth": {
            "type": "bearer",
            "token": "${API_TOKEN}"
        },
        "pagination": {
            "type": "cursor",
            "cursor_param": "next_cursor"
        }
    }
)
```

**Features:**
- Multiple authentication methods (API key, Bearer, OAuth2)
- Pagination handling (offset, cursor, link-based)
- Rate limiting and retry logic
- Response mapping configuration
- Webhook support for push-based updates

---

## Document Parsers

Format-specific parsers with automatic detection via registry.

### Parser Registry

```python
from ingestion.processors.parsers.registry import ParserRegistry

registry = ParserRegistry()

# Auto-detect parser from content/filename
parser = registry.get_parser(filename="report.pdf", content_type="application/pdf")

# Parse document
result = await parser.parse(content, metadata={"source_uri": "s3://bucket/report.pdf"})

# Result contains:
# - text: Extracted text content
# - metadata: Document metadata (title, author, page_count, etc.)
# - sections: Structured sections (if available)
```

### Supported Formats

| Format | Parser | Library | Features |
|--------|--------|---------|----------|
| PDF | `PDFParser` | PyMuPDF | Text extraction, tables, images, metadata |
| DOCX | `DocxParser` | python-docx | Paragraphs, tables, styles, headers |
| HTML | `HTMLParser` | BeautifulSoup4 | Content extraction, link preservation |
| Markdown | `MarkdownParser` | markdown-it-py | AST parsing, frontmatter (planned) |
| Plain Text | `TextParser` | Built-in | Encoding detection, line normalization |

### Custom Parser

```python
from ingestion.processors.parsers.base import BaseParser

class CustomParser(BaseParser):
    supported_extensions = [".xyz"]
    supported_mimetypes = ["application/x-xyz"]

    async def parse(self, content: bytes, metadata: dict = None) -> ParseResult:
        # Custom parsing logic
        text = self.extract_text(content)
        return ParseResult(
            text=text,
            metadata={"format": "xyz", **metadata}
        )

# Register custom parser
registry.register(CustomParser())
```

---

## Chunking Engine

Three chunking strategies optimized for different content types.

### Configuration

```python
from ingestion.processors.chunking import ChunkingEngine, ChunkingConfig

config = ChunkingConfig(
    strategy="recursive",  # recursive | semantic | hierarchical
    target_tokens=300,     # ~200-400 optimal range
    max_tokens=512,
    overlap_tokens=50,     # 10-20% overlap
    preserve_headings=True
)

engine = ChunkingEngine(config)
chunks = engine.chunk(document_text, metadata=doc_metadata)
```

### Strategies

#### Recursive Chunking (Default)
Best for general documents with clear paragraph structure.

```python
config = ChunkingConfig(
    strategy="recursive",
    separators=["\n\n", "\n", ". ", " "],
    target_tokens=300,
    max_tokens=512,
    overlap_tokens=50
)
```

#### Semantic Chunking
Uses spaCy sentence boundaries for semantically coherent chunks.

```python
config = ChunkingConfig(
    strategy="semantic",
    spacy_model="en_core_web_sm",
    similarity_threshold=0.7,
    target_tokens=300
)
```

#### Hierarchical Chunking
Creates parent-child relationships preserving document structure.

```python
config = ChunkingConfig(
    strategy="hierarchical",
    levels=["h1", "h2", "paragraph"],
    target_tokens=300,
    create_parent_chunks=True
)
```

### Chunk Output

```python
@dataclass
class Chunk:
    content: str
    index: int
    token_count: int
    metadata: dict  # Includes:
        # - parent_chunk_id (for hierarchical)
        # - section_heading
        # - start_char, end_char
        # - embedding_model, embedding_version
```

---

## Embedding Service

High-performance embedding generation with caching and batch processing.

### Configuration

```python
# config.py settings
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_BATCH_SIZE = 32
EMBEDDING_CACHE_TTL = 86400  # 24 hours
```

### Usage

```python
from ingestion.embedding.service import EmbeddingService

service = EmbeddingService(
    model_name="BAAI/bge-large-en-v1.5",
    cache_enabled=True,
    batch_size=32
)

# Single embedding
embedding = await service.embed("Search query text")

# Batch embedding with progress callback
embeddings = await service.embed_batch(
    texts=chunk_contents,
    show_progress=True
)

# Query embedding (with instruction prefix for BGE models)
query_embedding = await service.embed_query("What is RAG?")
```

### Caching

Embeddings are cached in Redis using content hash as key:

```python
from ingestion.embedding.cache import EmbeddingCache

cache = EmbeddingCache(redis_client)

# Cache lookup
cached = await cache.get(content_hash="sha256:abc123...")

# Cache store
await cache.set(
    content_hash="sha256:abc123...",
    embedding=vector,
    model="bge-large-en-v1.5",
    ttl=86400
)
```

### Model Migration

Zero-downtime embedding model migration:

```python
from ingestion.migrations.embedding_migrator import EmbeddingMigrator

migrator = EmbeddingMigrator(
    source_model="bge-large-en-v1.5",
    target_model="bge-m3",
    batch_size=100
)

# Start migration job
job_id = await migrator.start_migration(
    scope={"tenant_id": "uuid"},
    validation_samples=100
)

# Check progress
progress = await migrator.get_progress(job_id)
# {"processed": 5000, "total": 10000, "status": "running"}
```

---

## Index Writers

Coordinated writing to multiple stores for hybrid search support.

### Index Coordinator

```python
from ingestion.indexing.coordinator import IndexCoordinator

coordinator = IndexCoordinator(
    qdrant_client=qdrant,
    opensearch_client=opensearch,
    postgres_pool=db_pool
)

# Index chunks with embeddings
await coordinator.index(
    document_id="uuid",
    chunks=processed_chunks,
    embeddings=vectors,
    metadata=doc_metadata
)

# Atomic rollback on failure
await coordinator.delete_document("uuid")
```

### Qdrant Writer

```python
from ingestion.indexing.qdrant import QdrantIndexWriter

writer = QdrantIndexWriter(
    client=qdrant_client,
    collection="documents",
    vector_size=1024
)

await writer.upsert(
    points=[
        {
            "id": chunk_id,
            "vector": embedding,
            "payload": {
                "tenant_id": "uuid",
                "document_id": "uuid",
                "chunk_index": 0,
                "content": chunk_text[:500],  # Preview
                "allowed_groups": ["group1", "group2"]
            }
        }
    ]
)
```

### OpenSearch Writer

```python
from ingestion.indexing.opensearch import OpenSearchIndexWriter

writer = OpenSearchIndexWriter(
    client=opensearch_client,
    index="rag-chunks"
)

await writer.bulk_index(
    documents=[
        {
            "_id": chunk_id,
            "document_id": doc_id,
            "tenant_id": tenant_id,
            "content": chunk_text,
            "title": doc_title,
            "source_uri": source_uri
        }
    ]
)
```

---

## Metadata Enrichment

Automated metadata extraction and content analysis.

### Enrichment Pipeline

```python
from ingestion.processors.enrichment import EnrichmentPipeline

pipeline = EnrichmentPipeline(
    language_detection=True,
    pii_detection=True,
    metadata_extraction=True
)

enriched = await pipeline.enrich(
    content=document_text,
    metadata={"source_uri": "...", "tenant_id": "..."}
)

# enriched.metadata contains:
# - language: "en"
# - pii_detected: True
# - pii_types: ["EMAIL", "PHONE"]
# - word_count: 1500
# - reading_time_minutes: 6
# - detected_entities: [...]
```

### PII Detection

Uses Microsoft Presidio for entity detection:

```python
from ingestion.processors.enrichment.pii_detector import PIIDetector

detector = PIIDetector(
    entities=["EMAIL", "PHONE", "PERSON", "CREDIT_CARD"],
    language="en"
)

results = detector.detect(text)
# [PIIEntity(type="EMAIL", start=10, end=30, score=0.95)]

# Optional: Redact PII
redacted_text = detector.redact(text)
```

### Language Detection

```python
from ingestion.processors.enrichment.language_detector import LanguageDetector

detector = LanguageDetector()
language = detector.detect(text)  # "en", "es", "fr", etc.
```

---

## Async Processing

Celery-based task queue for scalable document processing.

### Task Queues

| Queue | Purpose | Priority |
|-------|---------|----------|
| `ingestion` | Document ingestion tasks | High |
| `embedding` | Embedding generation | Medium |
| `reembed` | Re-embedding jobs | Low |
| `dlq` | Dead letter queue | - |

### Celery Configuration

```python
# tasks/celery_app.py
celery_app = Celery(
    "ingestion",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1"
)

celery_app.conf.update(
    task_routes={
        "ingestion.tasks.ingest.*": {"queue": "ingestion"},
        "ingestion.tasks.reembed.*": {"queue": "reembed"}
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True
)
```

### Ingestion Task

```python
from ingestion.tasks.ingest import ingest_document

# Async task call
result = ingest_document.delay(
    source_config={
        "type": "filesystem",
        "path": "/data/documents/report.pdf"
    },
    tenant_id="uuid",
    options={
        "chunking_strategy": "recursive",
        "skip_pii_detection": False
    }
)

# Check status
status = result.status  # PENDING, STARTED, SUCCESS, FAILURE
```

### Job Status Tracking

```python
from ingestion.tasks.status import JobStatusTracker

tracker = JobStatusTracker(redis_client)

# Update progress
await tracker.update(
    job_id="uuid",
    status="processing",
    progress={"processed": 50, "total": 100}
)

# Get status
status = await tracker.get("uuid")
```

---

## API Reference

### Endpoints

#### Document Ingestion

```
POST /api/v1/ingest/sync
```

Start incremental sync from a source:

```json
{
  "source_type": "filesystem",
  "source_config": {
    "path": "/data/documents",
    "recursive": true
  },
  "options": {
    "chunking_strategy": "recursive",
    "target_tokens": 300
  }
}
```

Response:
```json
{
  "job_id": "uuid",
  "status": "queued",
  "estimated_documents": 150
}
```

#### Re-embedding

```
POST /api/v1/ingest/reembed
```

Start re-embedding job:

```json
{
  "target_model": "bge-m3",
  "scope": {
    "tenant_id": "uuid",
    "source_type": "filesystem"
  }
}
```

#### Job Status

```
GET /api/v1/ingest/jobs/{job_id}
```

Response:
```json
{
  "job_id": "uuid",
  "status": "processing",
  "progress": {
    "processed": 500,
    "total": 1000,
    "failed": 2
  },
  "started_at": "2024-01-15T10:30:00Z"
}
```

#### Document Management

```
GET /api/v1/documents
GET /api/v1/documents/{id}
DELETE /api/v1/documents/{id}
```

### Authentication

All endpoints require JWT authentication:

```
Authorization: Bearer <token>
```

Tenant isolation is enforced via the `tenant_id` claim in the JWT.

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ragpipeline
REDIS_URL=redis://localhost:6379/0

# Vector Store
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=documents

# Search
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_INDEX=rag-chunks

# Embedding
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
EMBEDDING_SERVICE_URL=http://localhost:8080
EMBEDDING_BATCH_SIZE=32
EMBEDDING_CACHE_TTL=86400

# Chunking
CHUNK_TARGET_TOKENS=300
CHUNK_MAX_TOKENS=512
CHUNK_OVERLAP_TOKENS=50

# Object Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rag-documents

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Telemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
PROMETHEUS_PORT=9090
```

### Settings Validation

The service validates configuration against architecture requirements at startup:

```python
# config.py
class Settings(BaseSettings):
    embedding_dimensions: int = 1024
    chunk_target_tokens: int = 300
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 50

    @validator("embedding_dimensions")
    def validate_dimensions(cls, v):
        if v != 1024:
            raise ValueError("Embedding dimensions must be 1024 for BGE-large")
        return v
```

---

## Observability

### Metrics (Prometheus)

```
# Counter: Documents ingested
ingestion_documents_total{tenant_id, source_type, status}

# Histogram: Ingestion latency
ingestion_duration_seconds{stage}  # parse, chunk, embed, index

# Gauge: Active jobs
ingestion_active_jobs{queue}

# Counter: Embeddings generated
embedding_requests_total{model, cached}
```

### Tracing (OpenTelemetry)

All operations are traced with span context:

- `ingest.parse` - Document parsing
- `ingest.chunk` - Chunking operation
- `ingest.embed` - Embedding generation
- `ingest.index` - Index writing

### Structured Logging

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Document ingested",
  "trace_id": "abc123",
  "span_id": "def456",
  "tenant_id": "uuid",
  "document_id": "uuid",
  "chunks_created": 15,
  "duration_ms": 1250
}
```

---

## Testing

### Run Tests

```bash
# All ingestion tests
cd services/ingestion
pytest

# Specific component
pytest connectors/tests/
pytest processors/tests/
pytest embedding/tests/
pytest indexing/tests/

# With coverage
pytest --cov=. --cov-report=html
```

### Test Coverage

| Component | Test Files | Coverage |
|-----------|------------|----------|
| Connectors | 5 files, 2662+ lines | 95%+ |
| Parsers | 2 files | 90%+ |
| Chunking | 1 file | 95%+ |
| Embedding | 4 files | 90%+ |
| Indexing | 3 files | 90%+ |
| Tasks | 4 files | 85%+ |
| API | 2 files | 90%+ |

---

## Deduplication & Versioning

### Content Hash Deduplication

Documents are deduplicated using SHA-256 content hash:

```python
import hashlib

content_hash = hashlib.sha256(document_bytes).hexdigest()
```

Database constraint ensures uniqueness:
```sql
UNIQUE (tenant_id, source_uri, content_hash)
```

### Version Tracking

- Same content = skip re-ingestion, return existing document ID
- New content for same URI = increment version, re-chunk/embed

```python
# Check for existing document
existing = await db.get_document_by_hash(tenant_id, source_uri, content_hash)
if existing:
    return existing.id  # Idempotent

# New version
new_version = await db.get_latest_version(tenant_id, source_uri) + 1
```

---

## Performance Targets

| Operation | Target (p95) |
|-----------|--------------|
| Parse document | 100ms |
| Chunk document | 50ms |
| Generate embedding | 20ms |
| Index to Qdrant | 30ms |
| Index to OpenSearch | 20ms |
| Total ingestion (1 doc) | 500ms |

---

## Troubleshooting

### Common Issues

**Celery workers not processing:**
```bash
# Check worker status
celery -A ingestion.tasks.celery_app inspect active

# Check queue lengths
celery -A ingestion.tasks.celery_app inspect reserved
```

**Embedding service timeout:**
```bash
# Increase batch size or timeout
EMBEDDING_BATCH_SIZE=16
EMBEDDING_TIMEOUT=60
```

**Memory issues with large documents:**
```bash
# Enable streaming for large files
STREAM_LARGE_FILES=true
LARGE_FILE_THRESHOLD_MB=100
```
