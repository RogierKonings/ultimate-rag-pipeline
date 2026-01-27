# Rust Ingestion: Embedding Client, Index Coordinator, Connectors Design

> **Date:** 2025-01-27
> **Phase:** 3.4-3.6 of Rust Migration
> **Scope:** Embedding Client, Multi-Store Index Coordinator, Filesystem/S3 Connectors

## Overview

This document describes the design for the next components of the Rust ingestion service:
- **P3.4 Embedding Client** - Thin HTTP client for embedding service
- **P3.5 Index Coordinator** - Parallel writes to Qdrant, OpenSearch, PostgreSQL
- **P3.6 Connectors** - Local filesystem and S3/MinIO document sources

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Embedding client architecture | Thin HTTP client | Single responsibility, matches rag-retrieval patterns |
| PostgreSQL status tracking | Use rag-database crate | Consistency, reuse connection pooling |
| Connector scope | Both local + S3 | Full feature parity with Python |

## Module Structure

```
crates/rag-ingestion/src/
├── lib.rs
├── error.rs              # Extend with new error variants
├── parsers/              # ✓ P3.1-P3.2 (done)
├── chunking/             # ✓ P3.3 (done)
├── embedding/            # P3.4 NEW
│   ├── mod.rs
│   ├── client.rs         # Thin HTTP client
│   └── config.rs         # EmbeddingClientConfig
├── indexing/             # P3.5 NEW
│   ├── mod.rs
│   ├── coordinator.rs    # IndexCoordinator
│   ├── models.rs         # DocumentRecord, IndexedChunk, WriteResult
│   └── status.rs         # IndexStatus enum
└── connectors/           # P3.6 NEW
    ├── mod.rs
    ├── base.rs           # Connector trait, DocumentMetadata, RawDocument
    ├── filesystem.rs     # FilesystemConnector (local)
    └── s3.rs             # S3Connector (MinIO/S3)
```

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| `reqwest` | 0.11 | HTTP client for embeddings |
| `aws-sdk-s3` | 1.x | S3/MinIO access |
| `aws-config` | 1.x | AWS credential loading |
| `tokio` | 1.x | Async runtime with `fs` feature |
| `mime_guess` | 2.0 | MIME type detection |
| `bytes` | 1.x | Efficient byte buffers |

## P3.4: Embedding Client

### Configuration

```rust
pub struct EmbeddingClientConfig {
    pub url: String,                    // e.g., "http://localhost:8080"
    pub endpoint: String,               // default: "/v1/embeddings"
    pub model: String,                  // default: "all-MiniLM-L6-v2"
    pub timeout: Duration,              // default: 30s
    pub max_retries: u32,               // default: 3
    pub retry_delay: Duration,          // default: 1s
}
```

### Client API

```rust
pub struct EmbeddingClient {
    client: reqwest::Client,
    config: EmbeddingClientConfig,
}

impl EmbeddingClient {
    pub async fn new(config: EmbeddingClientConfig) -> Result<Self>;

    /// Embed a batch of texts, returns (embeddings, token_count)
    pub async fn embed_batch(&self, texts: &[String]) -> Result<(Vec<Vec<f32>>, u32)>;

    /// Health check
    pub async fn health_check(&self) -> Result<bool>;
}
```

### Response Types (OpenAI-compatible)

```rust
pub struct EmbeddingResponse {
    pub data: Vec<EmbeddingData>,
    pub usage: Option<Usage>,
}

pub struct EmbeddingData {
    pub embedding: Vec<f32>,
    pub index: usize,
}

pub struct Usage {
    pub total_tokens: u32,
}
```

### Retry Logic

- Exponential backoff with jitter
- Retry on 5xx and connection errors
- Fail fast on 4xx (client errors)

## P3.5: Index Coordinator

### Status Tracking

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IndexStatus {
    Pending,    // Indexing in progress
    Ok,         // Successfully indexed
    Error,      // Indexing failed
    Stale,      // Needs re-indexing
}
```

### Models

```rust
pub struct DocumentRecord {
    pub document_id: DocumentId,
    pub tenant_id: TenantId,
    pub source_id: String,
    pub title: Option<String>,
    pub metadata: HashMap<String, Value>,
}

pub struct IndexedChunk {
    pub chunk_id: ChunkId,
    pub document_id: DocumentId,
    pub tenant_id: TenantId,
    pub content: String,
    pub embedding: Vec<f32>,
    pub chunk_index: u32,
    pub metadata: HashMap<String, Value>,
}

pub struct WriteResult {
    pub success: bool,
    pub items_written: usize,
    pub items_failed: usize,
    pub errors: Vec<String>,
    pub duration: Duration,
}
```

### Coordinator API

```rust
pub struct IndexCoordinator {
    qdrant: rag_vectorstore::VectorStoreClient,
    opensearch: rag_search::SearchClient,
    database: rag_database::DatabaseClient,
}

impl IndexCoordinator {
    pub async fn new(config: IndexCoordinatorConfig) -> Result<Self>;

    /// Index document and chunks to all stores in parallel
    pub async fn index_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>>;

    /// Delete document from all stores
    pub async fn delete_document(
        &self,
        document_id: DocumentId,
        tenant_id: TenantId,
    ) -> Result<HashMap<String, WriteResult>>;

    /// Re-index (delete then write)
    pub async fn reindex_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>>;
}
```

### Parallelism

Writes to all three stores happen via `tokio::join!`. Status tracking updates PostgreSQL after each operation completes.

## P3.6: Connectors

### Base Types

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceType {
    Local,
    S3,
}

pub struct DocumentMetadata {
    pub source_id: String,           // Relative path or S3 key
    pub source_type: SourceType,
    pub filename: String,
    pub mime_type: Option<String>,
    pub size_bytes: Option<u64>,
    pub created_at: Option<DateTime<Utc>>,
    pub modified_at: Option<DateTime<Utc>>,
    pub extra: HashMap<String, Value>,
}

pub struct RawDocument {
    pub content: Bytes,
    pub metadata: DocumentMetadata,
}
```

### Connector Trait

```rust
#[async_trait]
pub trait Connector: Send + Sync {
    async fn connect(&mut self) -> Result<()>;
    async fn disconnect(&mut self) -> Result<()>;
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>>;
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument>;
}
```

### Filesystem Connector

```rust
pub struct FilesystemConnector {
    config: FilesystemConfig,
    connected: bool,
}

pub struct FilesystemConfig {
    pub base_path: PathBuf,
    pub recursive: bool,              // default: true
    pub file_extensions: Option<Vec<String>>,  // e.g., [".pdf", ".md"]
}
```

Uses `tokio::fs` for async file operations, `mime_guess` for MIME detection.

### S3 Connector

```rust
pub struct S3Connector {
    config: S3Config,
    client: Option<aws_sdk_s3::Client>,
}

pub struct S3Config {
    pub bucket: String,
    pub prefix: Option<String>,
    pub endpoint_url: Option<String>,  // For MinIO
    pub region: String,                // default: "us-east-1"
    pub file_extensions: Option<Vec<String>>,
}
```

Uses `aws-sdk-s3` with custom endpoint for MinIO compatibility.

## Testing Strategy

1. **Embedding Client**: Mock HTTP responses with `wiremock`
2. **Index Coordinator**: Mock store clients, verify parallel execution
3. **Connectors**:
   - Filesystem: Use temp directories
   - S3: Use LocalStack or MinIO in tests

## Success Criteria

- All components pass unit tests
- Embedding client handles retries correctly
- Index coordinator writes to all stores in parallel
- Connectors can read from both local and S3 storage
- Feature parity with Python implementations
