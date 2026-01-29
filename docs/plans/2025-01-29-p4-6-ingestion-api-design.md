# P4.6 Ingestion API - Design Document

> **Created:** 2025-01-29
> **Phase:** 4.6 of Rust Migration
> **Risk:** Low-Medium
> **Effort:** 1-2 weeks

## Overview

Port the Python ingestion API to Rust using Axum, following the patterns established in `rag-retrieval/src/api/`. This creates the HTTP interface for the ingestion service that other Phase 4 components will plug into.

## Architecture

### Directory Structure

```
crates/rag-ingestion/src/api/
├── mod.rs           # Module exports
├── server.rs        # Axum server setup, router creation
├── state.rs         # AppState with shared components
├── types.rs         # Request/response types (Serde)
├── error.rs         # API error types and HTTP mapping
├── jobs.rs          # In-memory job tracker (Option B)
└── routes/
    ├── mod.rs
    ├── ingest.rs    # Ingestion job endpoints
    ├── documents.rs # Document CRUD endpoints
    └── health.rs    # Health/ready endpoints
```

### AppState Components

```rust
pub struct AppState {
    /// Index coordinator for multi-store writes
    pub index_coordinator: Arc<IndexCoordinator>,

    /// Embedding client for generating vectors
    pub embedding_client: Arc<EmbeddingClient>,

    /// Document repository for PostgreSQL operations
    pub document_repo: Arc<DocumentRepository>,

    /// Chunk repository for PostgreSQL operations
    pub chunk_repo: Arc<ChunkRepository>,

    /// In-memory job tracker
    pub job_tracker: Arc<JobTracker>,

    /// Service version
    pub version: String,
}
```

## API Endpoints

### Ingest Routes (`/api/v1/ingest`)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/` | `start_ingestion` | Start batch ingestion job (returns 202 + job_id) |
| GET | `/` | `list_active_jobs` | List all active jobs |
| POST | `/single` | `ingest_single_document` | Ingest single document |
| POST | `/sync` | `start_sync` | Start incremental sync |
| POST | `/reembed` | `start_reembed` | Start re-embedding job |
| GET | `/{job_id}` | `get_job_status` | Get job status and progress |
| DELETE | `/{job_id}` | `cancel_job` | Cancel running job |

### Document Routes (`/api/v1/documents`)

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/` | `list_documents` | List documents (paginated, filtered) |
| GET | `/sync-status` | `get_sync_status` | Get indexing sync status |
| GET | `/{document_id}` | `get_document` | Get document metadata |
| DELETE | `/{document_id}` | `delete_document` | Delete document + chunks |
| POST | `/{document_id}/reindex` | `reindex_document` | Re-process document |
| POST | `/batch-delete` | `batch_delete_documents` | Delete multiple documents |

### Health Routes

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/health` | `liveness` | Liveness check |
| GET | `/ready` | `readiness` | Readiness (checks DB, Qdrant, OpenSearch) |

## Job Tracking (Option B)

Background tasks with `tokio::spawn` + in-memory job tracking:

```rust
pub struct JobTracker {
    jobs: DashMap<Uuid, JobState>,
}

pub struct JobState {
    pub status: JobStatus,
    pub progress: Option<JobProgress>,
    pub documents_processed: u32,
    pub chunks_created: u32,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub error_message: Option<String>,
    pub errors: Vec<String>,
    pub cancel_token: CancellationToken,
}

pub enum JobStatus {
    Pending,
    Started,
    Progress,
    Success,
    Failure,
    Revoked,
}
```

**Job Lifecycle:**
1. `start_ingestion` creates `JobState` with `Pending` status
2. `tokio::spawn` begins processing, updates to `Started`
3. Progress updates via `JobTracker::update_progress()`
4. On completion: `Success` or `Failure`
5. `cancel_job` triggers `CancellationToken`

## Request/Response Types

### Core Enums

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Filesystem,
    Database,
    Web,
    Api,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ChunkingStrategy {
    Recursive,
    Semantic,
    Hierarchical,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Visibility {
    Public,
    Private,
    Group,
}
```

### Ingest Request/Response

```rust
#[derive(Debug, Deserialize)]
pub struct IngestRequest {
    pub source_type: SourceType,
    pub source_config: serde_json::Value,
    #[serde(default)]
    pub processing: ProcessingOptions,
    pub acl: ACLContext,
}

#[derive(Debug, Serialize)]
pub struct IngestResponse {
    pub job_id: Uuid,
    pub status: String,
    pub message: String,
    pub created_at: DateTime<Utc>,
}
```

### Document Types

```rust
#[derive(Debug, Serialize)]
pub struct DocumentResponse {
    pub document_id: Uuid,
    pub source_id: String,
    pub source_type: String,
    pub filename: Option<String>,
    pub mime_type: Option<String>,
    pub title: Option<String>,
    pub author: Option<String>,
    pub chunk_count: i32,
    pub total_tokens: i32,
    pub tenant_id: String,
    pub visibility: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub indexed_at: Option<DateTime<Utc>>,
    pub status: String,
}
```

## Error Handling

```rust
#[derive(Debug)]
pub enum ApiError {
    NotFound(String),
    BadRequest(String),
    Forbidden(String),
    Internal(String),
    ServiceUnavailable(String),
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let (status, message) = match self {
            ApiError::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
            ApiError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg),
            ApiError::Forbidden(msg) => (StatusCode::FORBIDDEN, msg),
            ApiError::Internal(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg),
            ApiError::ServiceUnavailable(msg) => (StatusCode::SERVICE_UNAVAILABLE, msg),
        };

        let body = Json(serde_json::json!({
            "error": message
        }));

        (status, body).into_response()
    }
}
```

## Dependencies

Add to `crates/rag-ingestion/Cargo.toml`:

```toml
[dependencies]
axum = { version = "0.7", features = ["macros"] }
tower = "0.4"
tower-http = { version = "0.5", features = ["cors", "trace", "timeout"] }
tokio-util = "0.7"  # For CancellationToken
dashmap = "5.5"     # For concurrent job map
```

## Testing Strategy

1. **Unit tests:** Mock dependencies, test handler logic
2. **Integration tests:** Test against real services with testcontainers
3. **Contract tests:** Verify request/response shapes match Python

## Implementation Order

1. `api/error.rs` - Error types
2. `api/types.rs` - Request/response structs
3. `api/jobs.rs` - Job tracker
4. `api/state.rs` - AppState
5. `api/routes/health.rs` - Health endpoints
6. `api/routes/documents.rs` - Document CRUD
7. `api/routes/ingest.rs` - Ingestion endpoints
8. `api/server.rs` - Router assembly
9. `api/mod.rs` - Module exports
10. `bin/ingestion-api.rs` - Binary entry point
