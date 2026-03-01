# Ingestion Service Documentation

**Language:** Rust (Axum) | **Port:** 8001 | **Implementation:** `crates/rag-ingestion/`

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
- [Multi-Store Indexing](#multi-store-indexing)
- [Configuration](#configuration)

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Ingestion Service (Rust/Axum)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   Source     │   │   Document   │   │   Chunking   │   │   Embedding  │  │
│  │  Connectors  │──▶│   Parsers    │──▶│    Engine    │──▶│   Client     │  │
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
│  │                   Redis-backed Async Worker System                     │  │
│  │  Queues: high_priority | normal | low_priority | dlq                  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```text
crates/rag-ingestion/
├── src/
│   ├── api/                    # Axum HTTP routes
│   │   ├── routes.rs           # Endpoint handlers
│   │   ├── state.rs            # Application state
│   │   └── models.rs           # Request/response models
│   ├── connectors/             # Source connectors
│   │   ├── base.rs             # Connector trait
│   │   ├── filesystem.rs       # Local filesystem connector
│   │   └── s3.rs               # S3/MinIO connector
│   ├── parsers/                # Document format parsers
│   │   ├── base.rs             # Parser trait
│   │   ├── pdf.rs              # PDF parsing
│   │   ├── docx.rs             # Office Open XML (DOCX)
│   │   ├── html.rs             # HTML/web page parsing
│   │   ├── markdown.rs         # Markdown with YAML frontmatter
│   │   ├── text.rs             # Plain text parsing
│   │   └── registry.rs         # Parser auto-detection registry
│   ├── chunking/               # Text chunking strategies
│   │   ├── recursive.rs        # Recursive character splitter
│   │   └── config.rs           # Chunking configuration
│   ├── embedding/              # Embedding service client
│   │   ├── client.rs           # HTTP client to embedding service
│   │   └── cache.rs            # Redis embedding cache
│   ├── indexing/               # Multi-store index writers
│   │   ├── coordinator.rs      # Multi-store coordination
│   │   ├── qdrant.rs           # Qdrant vector writer
│   │   ├── opensearch.rs       # OpenSearch keyword writer
│   │   └── postgres.rs         # PostgreSQL metadata writer
│   ├── pii/                    # PII detection
│   │   ├── detector.rs         # PII pattern detection
│   │   └── config.rs           # Sensitivity configuration
│   ├── worker/                 # Redis-backed async job system
│   │   ├── queue.rs            # Priority queues with DLQ
│   │   ├── processor.rs        # Job processing
│   │   └── status.rs           # Job status tracking
│   ├── config.rs               # Service configuration
│   ├── error.rs                # Error types
│   └── lib.rs                  # Library root
├── Cargo.toml
├── Dockerfile
└── tests/                      # Integration tests
```

---

## Source Connectors

Two production-ready connectors for acquiring documents from various sources.

### Filesystem Connector

```rust
use rag_ingestion::connectors::{FilesystemConnector, ConnectorConfig};

let connector = FilesystemConnector::new(ConnectorConfig {
    path: "/data/documents".into(),
    recursive: true,
    include_patterns: vec!["*.pdf".into(), "*.docx".into()],
    exclude_patterns: vec!["*draft*".into(), "*temp*".into()],
});

// List available documents
let documents = connector.list_documents().await?;

// Fetch specific document
let doc = connector.fetch("report.pdf").await?;
```

**Features:**

- Local filesystem support
- Recursive directory traversal
- Glob pattern filtering (include/exclude)
- Automatic MIME type detection
- Metadata extraction (size, modified date)

### S3/MinIO Connector

```rust
use rag_ingestion::connectors::{S3Connector, S3Config};

let connector = S3Connector::new(S3Config {
    endpoint: "http://minio:9000".into(),
    bucket: "documents".into(),
    prefix: Some("tenant-123/".into()),
    access_key: env::var("MINIO_ACCESS_KEY")?,
    secret_key: env::var("MINIO_SECRET_KEY")?,
});

// List objects in bucket
let objects = connector.list_objects().await?;

// Fetch specific object
let content = connector.fetch("report.pdf").await?;
```

**Features:**

- S3-compatible storage (AWS S3, MinIO, etc.)
- Prefix-based filtering
- Streaming downloads for large files
- Automatic retry with exponential backoff
- Presigned URL generation

---

## Document Parsers

Format-specific parsers with automatic detection via registry.

### Parser Registry

```rust
use rag_ingestion::parsers::{ParserRegistry, ParseResult};

let registry = ParserRegistry::new();

// Auto-detect parser from content/filename
let parser = registry.get_parser("report.pdf", Some("application/pdf"))?;

// Parse document
let result: ParseResult = parser.parse(&content, metadata).await?;

// Result contains:
// - text: Extracted text content
// - metadata: Document metadata (title, author, page_count, etc.)
// - sections: Structured sections (if available)
```

### Supported Formats

| Format | Parser | Library | Features |
|--------|--------|---------|----------|
| PDF | `PdfParser` | pdf-extract | Text extraction, metadata |
| DOCX | `DocxParser` | docx-rs | Paragraphs, tables, styles |
| HTML | `HtmlParser` | scraper | Content extraction, link preservation |
| Markdown | `MarkdownParser` | pulldown-cmark | AST parsing, YAML frontmatter |
| Plain Text | `TextParser` | Built-in | Encoding detection, line normalization |

### Custom Parser

```rust
use rag_ingestion::parsers::{Parser, ParseResult};
use async_trait::async_trait;

struct CustomParser;

#[async_trait]
impl Parser for CustomParser {
    fn supported_extensions(&self) -> &[&str] {
        &[".xyz"]
    }

    fn supported_mimetypes(&self) -> &[&str] {
        &["application/x-xyz"]
    }

    async fn parse(&self, content: &[u8], metadata: Option<Metadata>) -> Result<ParseResult> {
        let text = self.extract_text(content)?;
        Ok(ParseResult {
            text,
            metadata: metadata.unwrap_or_default(),
            sections: vec![],
        })
    }
}

// Register custom parser
registry.register(Box::new(CustomParser));
```

---

## Chunking Engine

Four chunking strategies. **Auto** (default) analyzes the document and picks the best concrete strategy.

### Strategies

**Auto** (default) — intelligent strategy selection based on document characteristics
(heading density, sentence length, prose fraction, file type, parser metadata).
This is the recommended option for most use cases.

**Recursive** — splits by separator hierarchy:
paragraphs → lines → sentences → words → characters.
Best for: short docs, unstructured text, code-heavy content.

**Semantic** — splits by Unicode sentence boundaries, groups sentences to target size.
Best for: long prose, academic/legal text with complex sentences.

**Hierarchical** — detects headings (Markdown `#`, numbered, ALL CAPS, colon-terminated),
splits into sections, then recursive-chunks within each.
Best for: structured documents with clear sections (reports, manuals, specs).

### Automatic Strategy Selection

The default strategy is `"auto"`. When active, the worker analyzes the document
to pick the best concrete strategy. Signals used:

- File extension (`.md` with headings → Hierarchical)
- Structured blocks from parser (heading metadata → Hierarchical)
- Heading density in text (high → Hierarchical)
- Sentence length and prose fraction (long sentences + heavy prose → Semantic)
- Document length (short → Recursive)
- Default fallback → Recursive

Callers can override explicitly: `"chunking_strategy": "recursive|semantic|hierarchical"`. Omitting the field defaults to `"auto"`.

### Configuration

```rust
use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingConfig};

let config = ChunkingConfig {
    target_tokens: 300,      // ~200-400 optimal range
    max_tokens: 512,
    chunk_overlap: 50,       // 10-20% overlap
    min_chunk_size: 50,
    tokenizer: "cl100k_base".into(),
};

let splitter = RecursiveCharacterSplitter::new(config)?;
let chunks = splitter.chunk(&document_text, document_id, None)?;
```

### Recursive Chunking Algorithm

1. Try to split on the first separator (paragraph breaks)
2. If chunks are still too large, recursively split with next separator
3. Continue until all chunks are within `max_tokens`
4. Merge small chunks up to `target_tokens`
5. Apply overlap between adjacent chunks

### Chunk Output

```rust
#[derive(Debug, Clone, Serialize)]
pub struct Chunk {
    pub content: String,
    pub index: usize,
    pub token_count: usize,
    pub metadata: ChunkMetadata,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkMetadata {
    pub section_heading: Option<String>,
    pub start_char: usize,
    pub end_char: usize,
    pub document_id: Uuid,
}
```

---

## Embedding Service

The ingestion service calls the separate Embedding Service (port 8080) for vector generation.

### Configuration

```bash
# Environment variables
EMBEDDING_SERVICE_URL=http://embedding-service:8080
EMBEDDING_BATCH_SIZE=32
EMBEDDING_CACHE_TTL=86400  # 24 hours
```

### Embedding Client

```rust
use rag_ingestion::embedding::EmbeddingClient;

let client = EmbeddingClient::new(
    "http://embedding-service:8080",
    Some(redis_client),  // Optional cache
);

// Single embedding
let embedding = client.embed("Search query text").await?;

// Batch embedding
let embeddings = client.embed_batch(&chunk_contents).await?;
```

### Caching

Embeddings are cached in Redis using content hash as key:

```rust
use rag_ingestion::embedding::EmbeddingCache;
use sha2::{Sha256, Digest};

let cache = EmbeddingCache::new(redis_client);

// Generate content hash
let hash = format!("{:x}", Sha256::digest(content.as_bytes()));

// Cache lookup
if let Some(cached) = cache.get(&hash).await? {
    return Ok(cached);
}

// Generate and cache
let embedding = client.embed(content).await?;
cache.set(&hash, &embedding, Duration::from_secs(86400)).await?;
```

### Re-embedding Jobs

Trigger re-embedding when changing embedding models:

```bash
# API call to start re-embedding job
curl -X POST http://localhost:8001/api/v1/ingest/reembed \
  -H "Content-Type: application/json" \
  -d '{
    "scope": {"tenant_id": "uuid"},
    "batch_size": 100
  }'
```

---

## Index Writers

Coordinated writing to multiple stores for hybrid search support.

### Index Coordinator

```rust
use rag_ingestion::indexing::IndexCoordinator;

let coordinator = IndexCoordinator::new(
    qdrant_client,
    opensearch_client,
    postgres_pool,
);

// Index chunks with embeddings (parallel writes)
coordinator.index(IndexRequest {
    document_id,
    chunks: processed_chunks,
    embeddings: vectors,
    metadata: doc_metadata,
}).await?;

// Atomic rollback on failure
coordinator.delete_document(document_id).await?;
```

### Qdrant Writer

```rust
use rag_ingestion::indexing::QdrantWriter;
use qdrant_client::qdrant::PointStruct;

let writer = QdrantWriter::new(
    qdrant_client,
    "documents",  // collection name
    384,          // vector size
);

let points = chunks.iter().zip(embeddings.iter()).map(|(chunk, embedding)| {
    PointStruct::new(
        chunk.id.to_string(),
        embedding.clone(),
        json!({
            "tenant_id": tenant_id,
            "document_id": document_id,
            "chunk_index": chunk.index,
            "content": &chunk.content[..500.min(chunk.content.len())],
            "allowed_groups": allowed_groups,
        }),
    )
}).collect();

writer.upsert(points).await?;
```

### OpenSearch Writer

```rust
use rag_ingestion::indexing::OpenSearchWriter;

let writer = OpenSearchWriter::new(
    opensearch_client,
    "rag-chunks",  // index name
);

let documents: Vec<_> = chunks.iter().map(|chunk| {
    json!({
        "_id": chunk.id,
        "document_id": document_id,
        "tenant_id": tenant_id,
        "content": chunk.content,
        "title": doc_title,
        "source_uri": source_uri,
    })
}).collect();

writer.bulk_index(documents).await?;
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

Redis-backed async worker system for scalable document processing.

### Task Queues

| Queue | Purpose | Priority |
|-------|---------|----------|
| `high_priority` | Urgent ingestion tasks | High |
| `normal` | Standard document ingestion | Medium |
| `low_priority` | Re-embedding, bulk jobs | Low |
| `dlq` | Dead letter queue | - |

### Worker Configuration

```rust
use rag_ingestion::worker::{WorkerPool, WorkerConfig};

let config = WorkerConfig {
    redis_url: "redis://localhost:6379".into(),
    queues: vec!["high_priority", "normal", "low_priority"],
    concurrency: 4,
    max_retries: 3,
    retry_delay: Duration::from_secs(60),
};

let pool = WorkerPool::new(config).await?;
pool.start().await?;
```

### Job Submission

```rust
use rag_ingestion::worker::{JobQueue, IngestJob};

let queue = JobQueue::new(redis_client);

// Submit ingestion job
let job_id = queue.submit(IngestJob {
    source_config: SourceConfig::Filesystem {
        path: "/data/documents/report.pdf".into(),
    },
    tenant_id,
    options: IngestOptions {
        chunking_strategy: "auto".into(),
        skip_pii_detection: false,
    },
}, Priority::Normal).await?;

// Check status
let status = queue.get_status(job_id).await?;
// JobStatus { state: Processing, progress: 50, total: 100 }
```

### Job Status Tracking

```rust
use rag_ingestion::worker::JobStatusTracker;

let tracker = JobStatusTracker::new(redis_client);

// Update progress
tracker.update(UpdateStatus {
    job_id,
    state: JobState::Processing,
    progress: Some(50),
    total: Some(100),
    error: None,
}).await?;

// Get status
let status = tracker.get(job_id).await?;
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
    "chunking_strategy": "auto",
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

## Multi-Store Indexing

The ingestion service implements a robust multi-store indexing architecture that ensures consistency across Qdrant (vectors), OpenSearch (keywords), and PostgreSQL (metadata).

### Key Features

- **Explicit Status Tracking**: Per-store status (`PENDING`, `OK`, `ERROR`, `STALE`) with retry metadata
- **Background Reconciliation**: Automated detection and repair of inconsistencies
- **Soft-Delete Propagation**: Cascading deletions across all stores via tombstone tasks
- **Early ACL Filtering**: Query-level access control enforcement
- **Tenant Index Isolation**: Optional dedicated collections/indices for large tenants

### Index Status Model

Each document tracks indexing status per store:

```python
class IndexStatus(str, Enum):
    PENDING = "pending"   # Not yet indexed or in progress
    OK = "ok"             # Successfully indexed
    ERROR = "error"       # Indexing failed (see last_index_error)
    STALE = "stale"       # Source updated, re-indexing needed
```

### Directory Structure (Additional)

```
services/ingestion/
├── tasks/
│   ├── reconcile.py     # Background index reconciliation
│   └── tombstone.py     # Soft-delete propagation
└── indexing/
    └── coordinator.py   # Multi-store coordination with status tracking
```

### Background Tasks

| Task | Schedule | Purpose |
| ---- | -------- | ------- |
| `reconcile_indexes` | Every 5 min | Detect and repair store inconsistencies |
| `process_tombstones` | Every 1 min | Propagate deletions to all stores |

### Related Documentation

For comprehensive details on multi-store indexing, including:

- State machine specifications
- Reconciliation algorithms
- ACL filtering implementation
- Tenant isolation modes
- Prometheus metrics
- Troubleshooting guides

See: **[Multi-Store Indexing Documentation](./multi-store-indexing.md)**

For per-tenant rate limiting, including:

- Concurrency limits configuration
- Priority queue setup (high/normal/low)
- Admin API for tenant limits management
- Prometheus metrics for monitoring

See: **[Rate Limiting Documentation](./rate-limiting.md)**

---

## Configuration

### Environment Variables

```bash
# Service
INGESTION_LISTEN_ADDR=0.0.0.0:8001

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/ragpipeline
REDIS_URL=redis://localhost:6379/0

# Vector Store
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=documents

# Search
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=rag-chunks

# Embedding Service
EMBEDDING_SERVICE_URL=http://localhost:8080
EMBEDDING_BATCH_SIZE=32
EMBEDDING_CACHE_TTL=86400

# Chunking
CHUNK_TARGET_TOKENS=300
CHUNK_MAX_TOKENS=512
CHUNK_OVERLAP_TOKENS=50

# Object Storage
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=rag-documents

# Worker
WORKER_CONCURRENCY=4
WORKER_MAX_RETRIES=3

# Telemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
METRICS_PORT=9090
```

### Configuration Struct

```rust
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct IngestionConfig {
    pub listen_addr: SocketAddr,
    pub database_url: String,
    pub redis_url: String,
    pub qdrant_url: String,
    pub opensearch_url: String,
    pub embedding_service_url: String,

    #[serde(default = "default_chunk_target")]
    pub chunk_target_tokens: usize,  // default: 300

    #[serde(default = "default_chunk_max")]
    pub chunk_max_tokens: usize,     // default: 512

    #[serde(default = "default_chunk_overlap")]
    pub chunk_overlap_tokens: usize, // default: 50
}
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
cd crates
cargo test -p rag-ingestion

# Specific module
cargo test -p rag-ingestion connectors::
cargo test -p rag-ingestion parsers::
cargo test -p rag-ingestion chunking::
cargo test -p rag-ingestion indexing::

# With coverage (requires cargo-tarpaulin)
cargo tarpaulin -p rag-ingestion --out Html

# Linting
cargo clippy -p rag-ingestion -- -D warnings
```

### Test Coverage

| Component | Coverage |
|-----------|----------|
| Connectors | 90%+ |
| Parsers | 90%+ |
| Chunking | 95%+ |
| Embedding Client | 90%+ |
| Indexing | 90%+ |
| Worker | 85%+ |
| API | 90%+ |

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

**Workers not processing jobs:**

```bash
# Check Redis connection
redis-cli ping

# Check queue lengths
redis-cli LLEN ingestion:queue:normal

# Check DLQ for failed jobs
redis-cli LLEN ingestion:queue:dlq
```

**Embedding service timeout:**

```bash
# Increase timeout or reduce batch size
EMBEDDING_TIMEOUT_MS=30000
EMBEDDING_BATCH_SIZE=16
```

**Memory issues with large documents:**

```bash
# The service streams large files automatically
# Adjust the threshold if needed
LARGE_FILE_THRESHOLD_MB=100
```

**Qdrant connection issues:**

```bash
# Check Qdrant health
curl http://localhost:6333/health

# Verify collection exists
curl http://localhost:6333/collections/documents
```
