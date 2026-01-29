# P4.6 Ingestion API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the Python ingestion API to Rust, creating `/api/v1/ingest` and `/api/v1/documents` endpoints with in-memory job tracking.

**Architecture:** Axum-based HTTP service following patterns from `rag-retrieval/src/api/`. Background job processing via `tokio::spawn` with `DashMap` for concurrent job state tracking. Mirrors Python FastAPI endpoints exactly.

**Tech Stack:** Axum 0.7, tower-http (CORS, tracing, timeout), dashmap, tokio-util (CancellationToken), serde, uuid, chrono

---

## Task 1: Add API Dependencies to Cargo.toml

**Files:**
- Modify: `crates/rag-ingestion/Cargo.toml`

**Step 1: Add Axum and related dependencies**

Add these dependencies after the existing ones in `Cargo.toml`:

```toml
# API server
axum = { version = "0.7", features = ["macros"] }
tower = "0.4"
tower-http = { version = "0.5", features = ["cors", "trace", "timeout"] }

# Job tracking
dashmap = "5.5"
tokio-util = { version = "0.7", features = ["rt"] }
```

**Step 2: Verify dependencies resolve**

Run: `cd crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds with no errors

**Step 3: Commit**

```bash
git add crates/rag-ingestion/Cargo.toml
git commit -m "feat(rag-ingestion): add API dependencies for Axum server"
```

---

## Task 2: Create API Error Types

**Files:**
- Create: `crates/rag-ingestion/src/api/error.rs`
- Create: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Write the test file for error types**

Create `crates/rag-ingestion/tests/api_error_tests.rs`:

```rust
use axum::http::StatusCode;
use rag_ingestion::api::error::{ApiError, ApiResult};

#[test]
fn test_bad_request_error() {
    let err = ApiError::bad_request("Invalid input");
    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(err.code, "BAD_REQUEST");
}

#[test]
fn test_not_found_error() {
    let err = ApiError::not_found("Job not found");
    assert_eq!(err.status, StatusCode::NOT_FOUND);
    assert_eq!(err.code, "NOT_FOUND");
}

#[test]
fn test_forbidden_error() {
    let err = ApiError::forbidden("Access denied");
    assert_eq!(err.status, StatusCode::FORBIDDEN);
    assert_eq!(err.code, "FORBIDDEN");
}

#[test]
fn test_error_with_details() {
    let err = ApiError::validation("Field error")
        .with_details(serde_json::json!({"field": "tenant_id"}));
    assert!(err.details.is_some());
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion --test api_error_tests`
Expected: FAIL - module not found

**Step 3: Create the api module structure**

Create `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.

pub mod error;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
```

**Step 4: Create the error module**

Create `crates/rag-ingestion/src/api/error.rs`:

```rust
//! API error handling for the ingestion service.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};

use crate::error::IngestionError;

/// API error that can be converted to an HTTP response.
#[derive(Debug, Clone)]
pub struct ApiError {
    /// HTTP status code.
    pub status: StatusCode,
    /// Human-readable error message.
    pub message: String,
    /// Error code for programmatic handling.
    pub code: String,
    /// Optional details for debugging.
    pub details: Option<serde_json::Value>,
}

impl ApiError {
    /// Create a new API error.
    #[must_use]
    pub fn new(status: StatusCode, code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            status,
            code: code.into(),
            message: message.into(),
            details: None,
        }
    }

    /// Add details to the error.
    #[must_use]
    pub fn with_details(mut self, details: serde_json::Value) -> Self {
        self.details = Some(details);
        self
    }

    /// Create a bad request error (400).
    #[must_use]
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "BAD_REQUEST", message)
    }

    /// Create a validation error (400).
    #[must_use]
    pub fn validation(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "VALIDATION_ERROR", message)
    }

    /// Create a forbidden error (403).
    #[must_use]
    pub fn forbidden(message: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, "FORBIDDEN", message)
    }

    /// Create a not found error (404).
    #[must_use]
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, "NOT_FOUND", message)
    }

    /// Create an internal server error (500).
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", message)
    }

    /// Create a service unavailable error (503).
    #[must_use]
    pub fn service_unavailable(message: impl Into<String>) -> Self {
        Self::new(StatusCode::SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", message)
    }
}

/// JSON error response body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorResponse {
    /// The error details.
    pub error: ErrorBody,
}

/// Error body within the response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorBody {
    /// Error code for programmatic handling.
    pub code: String,
    /// Human-readable error message.
    pub message: String,
    /// Optional additional details.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = ErrorResponse {
            error: ErrorBody {
                code: self.code,
                message: self.message,
                details: self.details,
            },
        };
        (self.status, Json(body)).into_response()
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {} ({})", self.code, self.message, self.status)
    }
}

impl std::error::Error for ApiError {}

impl From<IngestionError> for ApiError {
    fn from(err: IngestionError) -> Self {
        match &err {
            IngestionError::NotFound(msg) => Self::not_found(msg),
            IngestionError::InvalidInput(msg) => Self::bad_request(msg),
            IngestionError::Parse(_) => Self::internal(err.to_string()),
            IngestionError::Embedding(_) => Self::internal(err.to_string()),
            IngestionError::Chunking(_) => Self::internal(err.to_string()),
            IngestionError::VectorStore(_) => Self::internal(err.to_string()),
            IngestionError::Search(_) => Self::internal(err.to_string()),
            IngestionError::Database(_) => Self::internal(err.to_string()),
            IngestionError::Storage(_) => Self::internal(err.to_string()),
            IngestionError::Io(_) => Self::internal(err.to_string()),
        }
    }
}

/// Result type for API operations.
pub type ApiResult<T> = Result<T, ApiError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_error_creation() {
        let err = ApiError::bad_request("Invalid query parameter");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.code, "BAD_REQUEST");
    }

    #[test]
    fn test_api_error_with_details() {
        let err = ApiError::validation("Field validation failed")
            .with_details(serde_json::json!({"field": "query"}));
        assert!(err.details.is_some());
    }

    #[test]
    fn test_api_error_into_response() {
        let err = ApiError::not_found("Resource not found");
        let response = err.into_response();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn test_api_error_display() {
        let err = ApiError::internal("Something went wrong");
        let display = err.to_string();
        assert!(display.contains("INTERNAL_ERROR"));
    }
}
```

**Step 5: Update lib.rs to export api module**

Add to `crates/rag-ingestion/src/lib.rs`:

```rust
pub mod api;
```

**Step 6: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion api_error`
Expected: All tests pass

**Step 7: Commit**

```bash
git add crates/rag-ingestion/src/api/ crates/rag-ingestion/src/lib.rs crates/rag-ingestion/tests/
git commit -m "feat(rag-ingestion): add API error types"
```

---

## Task 3: Create API Request/Response Types

**Files:**
- Create: `crates/rag-ingestion/src/api/types.rs`
- Modify: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Write tests for API types**

Create `crates/rag-ingestion/tests/api_types_tests.rs`:

```rust
use rag_ingestion::api::types::*;
use uuid::Uuid;

#[test]
fn test_source_type_serialization() {
    let source = SourceType::Filesystem;
    let json = serde_json::to_string(&source).unwrap();
    assert_eq!(json, "\"filesystem\"");
}

#[test]
fn test_ingest_request_deserialization() {
    let json = r#"{
        "source_type": "filesystem",
        "source_config": {"path": "/data"},
        "acl": {"tenant_id": "tenant-1"}
    }"#;
    let request: IngestRequest = serde_json::from_str(json).unwrap();
    assert_eq!(request.source_type, SourceType::Filesystem);
    assert_eq!(request.acl.tenant_id, "tenant-1");
}

#[test]
fn test_job_status_serialization() {
    let status = JobStatus::Progress;
    let json = serde_json::to_string(&status).unwrap();
    assert_eq!(json, "\"progress\"");
}

#[test]
fn test_ingest_response_serialization() {
    let response = IngestResponse {
        job_id: Uuid::nil(),
        status: "pending".into(),
        message: "Job started".into(),
        created_at: chrono::Utc::now(),
    };
    let json = serde_json::to_string(&response).unwrap();
    assert!(json.contains("\"job_id\""));
    assert!(json.contains("\"pending\""));
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion --test api_types_tests`
Expected: FAIL - types module not found

**Step 3: Create the types module**

Create `crates/rag-ingestion/src/api/types.rs`:

```rust
//! Request and response types for the ingestion API.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ============================================================================
// Enums
// ============================================================================

/// Supported source types for document ingestion.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Filesystem,
    Database,
    Web,
    Api,
}

/// Available chunking strategies.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ChunkingStrategy {
    #[default]
    Recursive,
    Semantic,
    Hierarchical,
}

/// Document visibility levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Visibility {
    Public,
    #[default]
    Private,
    Group,
}

/// Job status values.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobStatus {
    Pending,
    Started,
    Progress,
    Success,
    Failure,
    Revoked,
}

/// Index status values for stores.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum IndexStatusValue {
    Pending,
    Ok,
    Error,
    Stale,
}

/// Filter options for sync status queries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SyncStatusFilter {
    #[default]
    All,
    Ok,
    Error,
    Pending,
    AnyError,
}

// ============================================================================
// Ingest Request/Response Types
// ============================================================================

/// Processing options for document ingestion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessingOptions {
    #[serde(default)]
    pub chunking_strategy: ChunkingStrategy,
    #[serde(default = "default_chunk_size")]
    pub chunk_size: u32,
    #[serde(default = "default_chunk_overlap")]
    pub chunk_overlap: u32,
    #[serde(default = "default_pii_detection")]
    pub enable_pii_detection: bool,
    #[serde(default)]
    pub custom_metadata: serde_json::Value,
}

fn default_chunk_size() -> u32 { 512 }
fn default_chunk_overlap() -> u32 { 50 }
fn default_pii_detection() -> bool { true }

impl Default for ProcessingOptions {
    fn default() -> Self {
        Self {
            chunking_strategy: ChunkingStrategy::default(),
            chunk_size: default_chunk_size(),
            chunk_overlap: default_chunk_overlap(),
            enable_pii_detection: default_pii_detection(),
            custom_metadata: serde_json::Value::Object(Default::default()),
        }
    }
}

/// Access control context for ingested documents.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ACLContext {
    pub tenant_id: String,
    #[serde(default)]
    pub visibility: Visibility,
    #[serde(default)]
    pub allowed_groups: Vec<String>,
    #[serde(default)]
    pub allowed_users: Vec<String>,
}

/// Request to start an ingestion job.
#[derive(Debug, Clone, Deserialize)]
pub struct IngestRequest {
    pub source_type: SourceType,
    pub source_config: serde_json::Value,
    #[serde(default)]
    pub processing: ProcessingOptions,
    pub acl: ACLContext,
}

/// Request to ingest a single document.
#[derive(Debug, Clone, Deserialize)]
pub struct SingleIngestRequest {
    pub source_type: String,
    pub source_id: String,
    pub source_config: serde_json::Value,
    #[serde(default)]
    pub processing: ProcessingOptions,
    pub acl: ACLContext,
}

/// Response after starting an ingestion job.
#[derive(Debug, Clone, Serialize)]
pub struct IngestResponse {
    pub job_id: Uuid,
    pub status: String,
    pub message: String,
    pub created_at: DateTime<Utc>,
}

// ============================================================================
// Job Status Types
// ============================================================================

/// Progress information for a running job.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JobProgress {
    #[serde(default)]
    pub current: u32,
    #[serde(default)]
    pub total: u32,
    #[serde(default)]
    pub stage: String,
    #[serde(default)]
    pub percentage: f64,
}

/// Response for job status query.
#[derive(Debug, Clone, Serialize)]
pub struct JobStatusResponse {
    pub job_id: Uuid,
    pub status: JobStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub progress: Option<JobProgress>,
    #[serde(default)]
    pub documents_processed: u32,
    #[serde(default)]
    pub chunks_created: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_seconds: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
    #[serde(default)]
    pub errors: Vec<String>,
}

/// Response for listing active jobs.
#[derive(Debug, Clone, Serialize)]
pub struct ActiveJobsResponse {
    pub jobs: Vec<JobStatusResponse>,
    pub total: usize,
}

/// Response for job cancellation.
#[derive(Debug, Clone, Serialize)]
pub struct CancelJobResponse {
    pub job_id: Uuid,
    pub cancelled: bool,
}

// ============================================================================
// Sync & Reembed Types
// ============================================================================

/// Configuration for incremental sync source.
#[derive(Debug, Clone, Deserialize)]
pub struct SyncSourceConfig {
    pub connection_string: Option<String>,
    pub table: Option<String>,
    pub updated_since: Option<DateTime<Utc>>,
    pub path: Option<String>,
    pub start_urls: Option<Vec<String>>,
    pub base_url: Option<String>,
}

/// Request to trigger incremental sync.
#[derive(Debug, Clone, Deserialize)]
pub struct SyncRequest {
    pub tenant_id: String,
    pub source_type: SourceType,
    pub source_config: SyncSourceConfig,
}

/// Response after starting an incremental sync job.
#[derive(Debug, Clone, Serialize)]
pub struct SyncResponse {
    pub job_id: Uuid,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub estimated_completion: Option<DateTime<Utc>>,
    pub message: String,
}

/// Target scope for re-embedding job.
#[derive(Debug, Clone, Deserialize)]
pub struct ReembedTargetScope {
    pub tenant_id: Option<String>,
    pub source_types: Option<Vec<SourceType>>,
    pub document_ids: Option<Vec<Uuid>>,
}

/// Request to start re-embedding job.
#[derive(Debug, Clone, Deserialize)]
pub struct ReembedRequest {
    pub embedding_model: String,
    pub target_scope: ReembedTargetScope,
    #[serde(default = "default_batch_size")]
    pub batch_size: u32,
}

fn default_batch_size() -> u32 { 100 }

/// Response after starting a re-embedding job.
#[derive(Debug, Clone, Serialize)]
pub struct ReembedResponse {
    pub job_id: Uuid,
    pub embedding_job_id: Uuid,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub estimated_completion: Option<DateTime<Utc>>,
    pub message: String,
}

// ============================================================================
// Document Types
// ============================================================================

/// Document metadata response.
#[derive(Debug, Clone, Serialize)]
pub struct DocumentResponse {
    pub document_id: Uuid,
    pub source_id: String,
    pub source_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filename: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub author: Option<String>,
    pub chunk_count: i32,
    pub total_tokens: i32,
    pub tenant_id: String,
    pub visibility: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub indexed_at: Option<DateTime<Utc>>,
    pub status: String,
}

/// Paginated document list response.
#[derive(Debug, Clone, Serialize)]
pub struct DocumentListResponse {
    pub documents: Vec<DocumentResponse>,
    pub total: i64,
    pub page: i32,
    pub page_size: i32,
    pub pages: i32,
}

/// Response after deleting a document.
#[derive(Debug, Clone, Serialize)]
pub struct DocumentDeleteResponse {
    pub document_id: Uuid,
    pub deleted: bool,
    pub chunks_deleted: i64,
    pub message: String,
}

/// Request to delete multiple documents.
#[derive(Debug, Clone, Deserialize)]
pub struct BatchDeleteRequest {
    pub document_ids: Vec<Uuid>,
}

/// Response after batch deleting documents.
#[derive(Debug, Clone, Serialize)]
pub struct BatchDeleteResponse {
    pub deleted_count: i32,
    pub failed_count: i32,
    pub results: Vec<DocumentDeleteResponse>,
}

/// Request to reindex a document.
#[derive(Debug, Clone, Deserialize)]
pub struct ReindexRequest {
    pub chunking_strategy: Option<String>,
    pub chunk_size: Option<u32>,
    pub chunk_overlap: Option<u32>,
}

// ============================================================================
// Sync Status Types
// ============================================================================

/// Individual document's sync status across all stores.
#[derive(Debug, Clone, Serialize)]
pub struct DocumentSyncStatus {
    pub document_id: Uuid,
    pub source_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub qdrant_status: IndexStatusValue,
    pub opensearch_status: IndexStatusValue,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_indexed_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_index_error: Option<String>,
    pub index_attempts: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Aggregated counts by status.
#[derive(Debug, Clone, Serialize, Default)]
pub struct SyncStatusSummary {
    pub ok: i64,
    pub pending: i64,
    pub error: i64,
    pub stale: i64,
}

/// Response for sync status query.
#[derive(Debug, Clone, Serialize)]
pub struct SyncStatusResponse {
    pub summary: SyncStatusSummary,
    pub documents: Vec<DocumentSyncStatus>,
    pub total: i64,
    pub limit: i32,
    pub offset: i32,
}

// ============================================================================
// Health Types
// ============================================================================

/// Liveness probe response.
#[derive(Debug, Clone, Serialize, Default)]
pub struct LivenessResponse {
    #[serde(default = "default_alive")]
    pub status: String,
}

fn default_alive() -> String { "alive".into() }

impl Default for LivenessResponse {
    fn default() -> Self {
        Self { status: default_alive() }
    }
}

/// Readiness probe response.
#[derive(Debug, Clone, Serialize)]
pub struct ReadinessResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub degradation_mode: Option<String>,
}

impl Default for ReadinessResponse {
    fn default() -> Self {
        Self {
            status: "ready".into(),
            degradation_mode: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_source_type_serde() {
        assert_eq!(
            serde_json::to_string(&SourceType::Filesystem).unwrap(),
            "\"filesystem\""
        );
        assert_eq!(
            serde_json::from_str::<SourceType>("\"database\"").unwrap(),
            SourceType::Database
        );
    }

    #[test]
    fn test_job_status_serde() {
        assert_eq!(
            serde_json::to_string(&JobStatus::Progress).unwrap(),
            "\"progress\""
        );
    }

    #[test]
    fn test_processing_options_defaults() {
        let opts = ProcessingOptions::default();
        assert_eq!(opts.chunk_size, 512);
        assert_eq!(opts.chunk_overlap, 50);
        assert!(opts.enable_pii_detection);
    }

    #[test]
    fn test_ingest_request_parse() {
        let json = r#"{
            "source_type": "filesystem",
            "source_config": {"path": "/data"},
            "acl": {"tenant_id": "t1"}
        }"#;
        let req: IngestRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.source_type, SourceType::Filesystem);
        assert_eq!(req.acl.tenant_id, "t1");
        assert_eq!(req.processing.chunk_size, 512); // default
    }
}
```

**Step 4: Update api/mod.rs to export types**

Update `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.

pub mod error;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use types::*;
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion api_types`
Expected: All tests pass

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/api/
git commit -m "feat(rag-ingestion): add API request/response types"
```

---

## Task 4: Create Job Tracker

**Files:**
- Create: `crates/rag-ingestion/src/api/jobs.rs`
- Modify: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Write tests for job tracker**

Create `crates/rag-ingestion/tests/job_tracker_tests.rs`:

```rust
use rag_ingestion::api::jobs::{JobTracker, JobState};
use rag_ingestion::api::types::JobStatus;
use uuid::Uuid;

#[tokio::test]
async fn test_create_job() {
    let tracker = JobTracker::new();
    let job_id = tracker.create_job("tenant-1".into());

    let state = tracker.get_job(&job_id).unwrap();
    assert_eq!(state.status, JobStatus::Pending);
    assert_eq!(state.tenant_id, "tenant-1");
}

#[tokio::test]
async fn test_update_job_status() {
    let tracker = JobTracker::new();
    let job_id = tracker.create_job("tenant-1".into());

    tracker.update_status(&job_id, JobStatus::Started);
    let state = tracker.get_job(&job_id).unwrap();
    assert_eq!(state.status, JobStatus::Started);
}

#[tokio::test]
async fn test_update_progress() {
    let tracker = JobTracker::new();
    let job_id = tracker.create_job("tenant-1".into());

    tracker.update_progress(&job_id, 5, 10, "processing");
    let state = tracker.get_job(&job_id).unwrap();
    assert_eq!(state.progress.current, 5);
    assert_eq!(state.progress.total, 10);
    assert_eq!(state.progress.percentage, 50.0);
}

#[tokio::test]
async fn test_cancel_job() {
    let tracker = JobTracker::new();
    let job_id = tracker.create_job("tenant-1".into());

    let cancelled = tracker.cancel_job(&job_id);
    assert!(cancelled);

    let state = tracker.get_job(&job_id).unwrap();
    assert_eq!(state.status, JobStatus::Revoked);
}

#[tokio::test]
async fn test_list_active_jobs() {
    let tracker = JobTracker::new();
    let job1 = tracker.create_job("tenant-1".into());
    let job2 = tracker.create_job("tenant-1".into());

    tracker.update_status(&job1, JobStatus::Success);

    let active = tracker.list_active_jobs();
    assert_eq!(active.len(), 1);
    assert_eq!(active[0], job2);
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion --test job_tracker_tests`
Expected: FAIL - jobs module not found

**Step 3: Create the jobs module**

Create `crates/rag-ingestion/src/api/jobs.rs`:

```rust
//! In-memory job tracker for background ingestion tasks.

use std::sync::atomic::{AtomicU32, Ordering};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::api::types::{JobProgress, JobStatus};

/// State of a single ingestion job.
#[derive(Debug, Clone)]
pub struct JobState {
    /// Current job status.
    pub status: JobStatus,
    /// Progress information.
    pub progress: JobProgress,
    /// Number of documents processed.
    pub documents_processed: u32,
    /// Number of chunks created.
    pub chunks_created: u32,
    /// When the job started.
    pub started_at: Option<DateTime<Utc>>,
    /// When the job completed.
    pub completed_at: Option<DateTime<Utc>>,
    /// Error message if failed.
    pub error_message: Option<String>,
    /// List of non-fatal errors.
    pub errors: Vec<String>,
    /// Tenant that owns this job.
    pub tenant_id: String,
}

impl JobState {
    /// Create a new pending job state.
    pub fn new(tenant_id: String) -> Self {
        Self {
            status: JobStatus::Pending,
            progress: JobProgress::default(),
            documents_processed: 0,
            chunks_created: 0,
            started_at: None,
            completed_at: None,
            error_message: None,
            errors: Vec::new(),
            tenant_id,
        }
    }

    /// Calculate duration in seconds.
    pub fn duration_seconds(&self) -> Option<f64> {
        let started = self.started_at?;
        let ended = self.completed_at.unwrap_or_else(Utc::now);
        Some((ended - started).num_milliseconds() as f64 / 1000.0)
    }
}

/// Internal state including cancellation token.
struct InternalJobState {
    state: JobState,
    cancel_token: CancellationToken,
}

/// Thread-safe in-memory job tracker.
pub struct JobTracker {
    jobs: DashMap<Uuid, InternalJobState>,
    active_count: AtomicU32,
}

impl JobTracker {
    /// Create a new job tracker.
    #[must_use]
    pub fn new() -> Self {
        Self {
            jobs: DashMap::new(),
            active_count: AtomicU32::new(0),
        }
    }

    /// Create a new job and return its ID.
    pub fn create_job(&self, tenant_id: String) -> Uuid {
        let job_id = Uuid::new_v4();
        let state = InternalJobState {
            state: JobState::new(tenant_id),
            cancel_token: CancellationToken::new(),
        };
        self.jobs.insert(job_id, state);
        self.active_count.fetch_add(1, Ordering::SeqCst);
        job_id
    }

    /// Get a clone of the job state.
    pub fn get_job(&self, job_id: &Uuid) -> Option<JobState> {
        self.jobs.get(job_id).map(|r| r.state.clone())
    }

    /// Get the cancellation token for a job.
    pub fn get_cancel_token(&self, job_id: &Uuid) -> Option<CancellationToken> {
        self.jobs.get(job_id).map(|r| r.cancel_token.clone())
    }

    /// Update the status of a job.
    pub fn update_status(&self, job_id: &Uuid, status: JobStatus) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = status;

            // Track started/completed times
            match status {
                JobStatus::Started | JobStatus::Progress => {
                    if entry.state.started_at.is_none() {
                        entry.state.started_at = Some(Utc::now());
                    }
                }
                JobStatus::Success | JobStatus::Failure | JobStatus::Revoked => {
                    entry.state.completed_at = Some(Utc::now());
                    if was_active {
                        self.active_count.fetch_sub(1, Ordering::SeqCst);
                    }
                }
                JobStatus::Pending => {}
            }
        }
    }

    /// Update job progress.
    pub fn update_progress(&self, job_id: &Uuid, current: u32, total: u32, stage: &str) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.progress.current = current;
            entry.state.progress.total = total;
            entry.state.progress.stage = stage.into();
            entry.state.progress.percentage = if total > 0 {
                (current as f64 / total as f64) * 100.0
            } else {
                0.0
            };

            // Ensure status reflects progress
            if entry.state.status == JobStatus::Pending || entry.state.status == JobStatus::Started
            {
                entry.state.status = JobStatus::Progress;
                if entry.state.started_at.is_none() {
                    entry.state.started_at = Some(Utc::now());
                }
            }
        }
    }

    /// Update document and chunk counts.
    pub fn update_counts(&self, job_id: &Uuid, docs: u32, chunks: u32) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.documents_processed = docs;
            entry.state.chunks_created = chunks;
        }
    }

    /// Add an error to the job.
    pub fn add_error(&self, job_id: &Uuid, error: String) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.errors.push(error);
        }
    }

    /// Mark job as failed with error message.
    pub fn fail_job(&self, job_id: &Uuid, error: String) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Failure;
            entry.state.error_message = Some(error);
            entry.state.completed_at = Some(Utc::now());
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
        }
    }

    /// Mark job as successful.
    pub fn complete_job(&self, job_id: &Uuid) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Success;
            entry.state.completed_at = Some(Utc::now());
            entry.state.progress.percentage = 100.0;
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
        }
    }

    /// Cancel a job. Returns true if the job was found and cancelled.
    pub fn cancel_job(&self, job_id: &Uuid) -> bool {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            if is_active(entry.state.status) {
                entry.cancel_token.cancel();
                entry.state.status = JobStatus::Revoked;
                entry.state.completed_at = Some(Utc::now());
                self.active_count.fetch_sub(1, Ordering::SeqCst);
                return true;
            }
        }
        false
    }

    /// List all active job IDs.
    pub fn list_active_jobs(&self) -> Vec<Uuid> {
        self.jobs
            .iter()
            .filter(|r| is_active(r.state.status))
            .map(|r| *r.key())
            .collect()
    }

    /// Get the count of active jobs.
    pub fn active_count(&self) -> u32 {
        self.active_count.load(Ordering::SeqCst)
    }

    /// Remove completed jobs older than the given duration.
    pub fn cleanup_old_jobs(&self, max_age: chrono::Duration) {
        let cutoff = Utc::now() - max_age;
        self.jobs.retain(|_, v| {
            v.state
                .completed_at
                .map(|t| t > cutoff)
                .unwrap_or(true) // Keep active jobs
        });
    }
}

impl Default for JobTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// Check if a job status is considered active.
fn is_active(status: JobStatus) -> bool {
    matches!(
        status,
        JobStatus::Pending | JobStatus::Started | JobStatus::Progress
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_state_new() {
        let state = JobState::new("tenant-1".into());
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(state.tenant_id, "tenant-1");
        assert!(state.started_at.is_none());
    }

    #[test]
    fn test_tracker_create_and_get() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(tracker.active_count(), 1);
    }

    #[test]
    fn test_tracker_update_status() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_status(&job_id, JobStatus::Started);
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Started);
        assert!(state.started_at.is_some());
    }

    #[test]
    fn test_tracker_update_progress() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_progress(&job_id, 5, 10, "processing");
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Progress);
        assert_eq!(state.progress.current, 5);
        assert_eq!(state.progress.total, 10);
        assert_eq!(state.progress.percentage, 50.0);
    }

    #[test]
    fn test_tracker_complete_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());
        assert_eq!(tracker.active_count(), 1);

        tracker.complete_job(&job_id);
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Success);
        assert!(state.completed_at.is_some());
        assert_eq!(tracker.active_count(), 0);
    }

    #[test]
    fn test_tracker_fail_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.fail_job(&job_id, "Something went wrong".into());
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Failure);
        assert_eq!(state.error_message, Some("Something went wrong".into()));
    }

    #[test]
    fn test_tracker_cancel_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let cancelled = tracker.cancel_job(&job_id);
        assert!(cancelled);

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Revoked);

        // Can't cancel already cancelled job
        let cancelled_again = tracker.cancel_job(&job_id);
        assert!(!cancelled_again);
    }

    #[test]
    fn test_tracker_list_active_jobs() {
        let tracker = JobTracker::new();
        let job1 = tracker.create_job("tenant-1".into());
        let job2 = tracker.create_job("tenant-1".into());
        let _job3 = tracker.create_job("tenant-1".into());

        tracker.complete_job(&job1);

        let active = tracker.list_active_jobs();
        assert_eq!(active.len(), 2);
        assert!(!active.contains(&job1));
        assert!(active.contains(&job2));
    }

    #[test]
    fn test_is_active() {
        assert!(is_active(JobStatus::Pending));
        assert!(is_active(JobStatus::Started));
        assert!(is_active(JobStatus::Progress));
        assert!(!is_active(JobStatus::Success));
        assert!(!is_active(JobStatus::Failure));
        assert!(!is_active(JobStatus::Revoked));
    }
}
```

**Step 4: Update api/mod.rs**

Update `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.

pub mod error;
pub mod jobs;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use types::*;
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion job_tracker`
Expected: All tests pass

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/api/
git commit -m "feat(rag-ingestion): add in-memory job tracker"
```

---

## Task 5: Create AppState

**Files:**
- Create: `crates/rag-ingestion/src/api/state.rs`
- Modify: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Write tests for AppState**

Create `crates/rag-ingestion/tests/api_state_tests.rs`:

```rust
use rag_ingestion::api::state::AppStateBuilder;

#[test]
fn test_app_state_builder_missing_job_tracker() {
    let result = AppStateBuilder::new().build();
    assert!(result.is_err());
}

#[test]
fn test_app_state_version() {
    // Version should match Cargo.toml
    let version = env!("CARGO_PKG_VERSION");
    assert!(!version.is_empty());
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-ingestion --test api_state_tests`
Expected: FAIL - state module not found

**Step 3: Create the state module**

Create `crates/rag-ingestion/src/api/state.rs`:

```rust
//! Application state for the ingestion service.

use std::sync::Arc;

use crate::api::jobs::JobTracker;
use crate::embedding::EmbeddingClient;
use crate::indexing::IndexCoordinator;

/// Application state shared across all request handlers.
pub struct AppState {
    /// In-memory job tracker.
    pub job_tracker: Arc<JobTracker>,

    /// Index coordinator for multi-store writes (optional for tests).
    pub index_coordinator: Option<Arc<IndexCoordinator>>,

    /// Embedding client (optional for tests).
    pub embedding_client: Option<Arc<EmbeddingClient>>,

    /// Service version string.
    pub version: String,
}

impl AppState {
    /// Create a new AppState builder.
    #[must_use]
    pub fn builder() -> AppStateBuilder {
        AppStateBuilder::new()
    }

    /// Get the service version.
    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    /// Check if index coordinator is available.
    #[must_use]
    pub fn has_index_coordinator(&self) -> bool {
        self.index_coordinator.is_some()
    }

    /// Check if embedding client is available.
    #[must_use]
    pub fn has_embedding_client(&self) -> bool {
        self.embedding_client.is_some()
    }
}

impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("has_index_coordinator", &self.index_coordinator.is_some())
            .field("has_embedding_client", &self.embedding_client.is_some())
            .field("active_jobs", &self.job_tracker.active_count())
            .field("version", &self.version)
            .finish()
    }
}

/// Builder for constructing `AppState`.
pub struct AppStateBuilder {
    job_tracker: Option<Arc<JobTracker>>,
    index_coordinator: Option<Arc<IndexCoordinator>>,
    embedding_client: Option<Arc<EmbeddingClient>>,
    version: String,
}

impl AppStateBuilder {
    /// Create a new builder with default values.
    #[must_use]
    pub fn new() -> Self {
        Self {
            job_tracker: None,
            index_coordinator: None,
            embedding_client: None,
            version: env!("CARGO_PKG_VERSION").to_string(),
        }
    }

    /// Set the job tracker.
    #[must_use]
    pub fn job_tracker(mut self, tracker: Arc<JobTracker>) -> Self {
        self.job_tracker = Some(tracker);
        self
    }

    /// Set the index coordinator.
    #[must_use]
    pub fn index_coordinator(mut self, coordinator: Arc<IndexCoordinator>) -> Self {
        self.index_coordinator = Some(coordinator);
        self
    }

    /// Set the embedding client.
    #[must_use]
    pub fn embedding_client(mut self, client: Arc<EmbeddingClient>) -> Self {
        self.embedding_client = Some(client);
        self
    }

    /// Set the service version.
    #[must_use]
    pub fn version(mut self, version: impl Into<String>) -> Self {
        self.version = version.into();
        self
    }

    /// Build the AppState.
    ///
    /// # Errors
    ///
    /// Returns an error if the job tracker is not set.
    pub fn build(self) -> Result<AppState, AppStateBuilderError> {
        let job_tracker = self
            .job_tracker
            .ok_or(AppStateBuilderError::MissingComponent("job_tracker"))?;

        Ok(AppState {
            job_tracker,
            index_coordinator: self.index_coordinator,
            embedding_client: self.embedding_client,
            version: self.version,
        })
    }

    /// Build AppState with a new job tracker (convenience method).
    pub fn build_with_new_tracker(self) -> Result<AppState, AppStateBuilderError> {
        let builder = if self.job_tracker.is_none() {
            self.job_tracker(Arc::new(JobTracker::new()))
        } else {
            self
        };
        builder.build()
    }
}

impl Default for AppStateBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Error when building AppState.
#[derive(Debug, Clone)]
pub enum AppStateBuilderError {
    /// A required component is missing.
    MissingComponent(&'static str),
}

impl std::fmt::Display for AppStateBuilderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingComponent(name) => {
                write!(f, "Missing required component: {name}")
            }
        }
    }
}

impl std::error::Error for AppStateBuilderError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_state_builder_default() {
        let builder = AppStateBuilder::default();
        assert!(builder.job_tracker.is_none());
        assert!(builder.index_coordinator.is_none());
        assert!(builder.embedding_client.is_none());
    }

    #[test]
    fn test_app_state_builder_missing_job_tracker() {
        let result = AppStateBuilder::new().build();
        assert!(result.is_err());

        if let Err(AppStateBuilderError::MissingComponent(name)) = result {
            assert_eq!(name, "job_tracker");
        } else {
            panic!("Expected MissingComponent error");
        }
    }

    #[test]
    fn test_app_state_builder_with_tracker() {
        let tracker = Arc::new(JobTracker::new());
        let state = AppStateBuilder::new()
            .job_tracker(tracker)
            .build()
            .unwrap();

        assert!(!state.has_index_coordinator());
        assert!(!state.has_embedding_client());
    }

    #[test]
    fn test_app_state_builder_convenience() {
        let state = AppStateBuilder::new().build_with_new_tracker().unwrap();
        assert_eq!(state.job_tracker.active_count(), 0);
    }

    #[test]
    fn test_app_state_builder_error_display() {
        let err = AppStateBuilderError::MissingComponent("test");
        assert_eq!(err.to_string(), "Missing required component: test");
    }

    #[test]
    fn test_app_state_debug() {
        let state = AppStateBuilder::new().build_with_new_tracker().unwrap();
        let debug = format!("{:?}", state);
        assert!(debug.contains("AppState"));
        assert!(debug.contains("has_index_coordinator"));
    }
}
```

**Step 4: Update api/mod.rs**

Update `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.

pub mod error;
pub mod jobs;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::*;
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion api_state`
Expected: All tests pass

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/api/
git commit -m "feat(rag-ingestion): add API AppState with builder"
```

---

## Task 6: Create Health Route Handlers

**Files:**
- Create: `crates/rag-ingestion/src/api/routes/mod.rs`
- Create: `crates/rag-ingestion/src/api/routes/health.rs`
- Modify: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Create routes directory and mod.rs**

Create `crates/rag-ingestion/src/api/routes/mod.rs`:

```rust
//! API route handlers for the ingestion service.

pub mod health;

pub use health::{health, liveness, readiness};
```

**Step 2: Create health.rs**

Create `crates/rag-ingestion/src/api/routes/health.rs`:

```rust
//! Health check endpoints for the ingestion service.

use std::sync::Arc;

use axum::{extract::State, Json};

use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{LivenessResponse, ReadinessResponse};

/// Handle the GET /health/live endpoint (Kubernetes liveness probe).
pub async fn liveness() -> Json<LivenessResponse> {
    Json(LivenessResponse::default())
}

/// Handle the GET /health/ready endpoint (Kubernetes readiness probe).
pub async fn readiness(
    State(state): State<Arc<AppState>>,
) -> ApiResult<Json<ReadinessResponse>> {
    // Check if we have the required components
    let has_coordinator = state.has_index_coordinator();
    let has_embedding = state.has_embedding_client();

    // For now, we're ready if we have the job tracker (which we always do)
    // In production, you'd check actual service connectivity
    let ready = true; // Job tracker is always available

    if !ready {
        return Err(ApiError::service_unavailable(
            "Service not ready: required components unavailable",
        ));
    }

    let degradation_mode = if has_coordinator && has_embedding {
        None
    } else if !has_coordinator && !has_embedding {
        Some("minimal".into())
    } else if !has_coordinator {
        Some("no_indexing".into())
    } else {
        Some("no_embedding".into())
    };

    Ok(Json(ReadinessResponse {
        status: "ready".into(),
        degradation_mode,
    }))
}

/// Handle the GET /health endpoint (full health check).
pub async fn health(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let active_jobs = state.job_tracker.active_count();

    Json(serde_json::json!({
        "status": "healthy",
        "version": state.version(),
        "components": {
            "job_tracker": true,
            "index_coordinator": state.has_index_coordinator(),
            "embedding_client": state.has_embedding_client()
        },
        "metrics": {
            "active_jobs": active_jobs
        }
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::jobs::JobTracker;

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_liveness() {
        let response = liveness().await;
        assert_eq!(response.status, "alive");
    }

    #[tokio::test]
    async fn test_readiness_minimal() {
        let state = test_state();
        let result = readiness(State(state)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert_eq!(response.status, "ready");
        assert_eq!(response.degradation_mode, Some("minimal".into()));
    }

    #[tokio::test]
    async fn test_health() {
        let state = test_state();
        let response = health(State(state)).await;

        assert_eq!(response["status"], "healthy");
        assert!(response["components"]["job_tracker"].as_bool().unwrap());
    }
}
```

**Step 3: Update api/mod.rs**

Update `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.

pub mod error;
pub mod jobs;
pub mod routes;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::*;
```

**Step 4: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion routes::health`
Expected: All tests pass

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/api/routes/
git commit -m "feat(rag-ingestion): add health check route handlers"
```

---

## Task 7: Create Ingest Route Handlers

**Files:**
- Create: `crates/rag-ingestion/src/api/routes/ingest.rs`
- Modify: `crates/rag-ingestion/src/api/routes/mod.rs`

**Step 1: Create ingest.rs**

Create `crates/rag-ingestion/src/api/routes/ingest.rs`:

```rust
//! Ingestion job route handlers.

use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use chrono::Utc;
use uuid::Uuid;

use crate::api::error::{ApiError, ApiResult};
use crate::api::jobs::JobTracker;
use crate::api::state::AppState;
use crate::api::types::{
    ActiveJobsResponse, CancelJobResponse, IngestRequest, IngestResponse, JobProgress,
    JobStatus, JobStatusResponse, ReembedRequest, ReembedResponse, SingleIngestRequest,
    SyncRequest, SyncResponse,
};

/// POST /api/v1/ingest - Start a batch ingestion job.
pub async fn start_ingestion(
    State(state): State<Arc<AppState>>,
    Json(request): Json<IngestRequest>,
) -> ApiResult<(StatusCode, Json<IngestResponse>)> {
    // Create job in tracker
    let job_id = state.job_tracker.create_job(request.acl.tenant_id.clone());

    tracing::info!(
        job_id = %job_id,
        source_type = ?request.source_type,
        tenant_id = %request.acl.tenant_id,
        "Started ingestion job"
    );

    // TODO: Spawn actual processing task
    // For now, just return the job ID

    Ok((
        StatusCode::ACCEPTED,
        Json(IngestResponse {
            job_id,
            status: "pending".into(),
            message: "Ingestion job started".into(),
            created_at: Utc::now(),
        }),
    ))
}

/// POST /api/v1/ingest/single - Ingest a single document.
pub async fn ingest_single_document(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SingleIngestRequest>,
) -> ApiResult<(StatusCode, Json<IngestResponse>)> {
    let job_id = state.job_tracker.create_job(request.acl.tenant_id.clone());

    tracing::info!(
        job_id = %job_id,
        source_id = %request.source_id,
        tenant_id = %request.acl.tenant_id,
        "Started single document ingestion"
    );

    // TODO: Spawn actual processing task

    Ok((
        StatusCode::ACCEPTED,
        Json(IngestResponse {
            job_id,
            status: "pending".into(),
            message: "Document ingestion started".into(),
            created_at: Utc::now(),
        }),
    ))
}

/// GET /api/v1/ingest/{job_id} - Get job status.
pub async fn get_job_status(
    State(state): State<Arc<AppState>>,
    Path(job_id): Path<Uuid>,
) -> ApiResult<Json<JobStatusResponse>> {
    let job_state = state
        .job_tracker
        .get_job(&job_id)
        .ok_or_else(|| ApiError::not_found(format!("Job {job_id} not found")))?;

    let progress = if job_state.progress.total > 0 {
        Some(JobProgress {
            current: job_state.progress.current,
            total: job_state.progress.total,
            stage: job_state.progress.stage.clone(),
            percentage: job_state.progress.percentage,
        })
    } else {
        None
    };

    Ok(Json(JobStatusResponse {
        job_id,
        status: job_state.status,
        progress,
        documents_processed: job_state.documents_processed,
        chunks_created: job_state.chunks_created,
        started_at: job_state.started_at,
        completed_at: job_state.completed_at,
        duration_seconds: job_state.duration_seconds(),
        error_message: job_state.error_message,
        errors: job_state.errors,
    }))
}

/// DELETE /api/v1/ingest/{job_id} - Cancel a job.
pub async fn cancel_job(
    State(state): State<Arc<AppState>>,
    Path(job_id): Path<Uuid>,
) -> ApiResult<Json<CancelJobResponse>> {
    // Check if job exists
    let job_state = state
        .job_tracker
        .get_job(&job_id)
        .ok_or_else(|| ApiError::not_found(format!("Job {job_id} not found")))?;

    // Check if job can be cancelled
    if matches!(job_state.status, JobStatus::Success | JobStatus::Failure) {
        return Err(ApiError::bad_request("Cannot cancel a completed job"));
    }

    let cancelled = state.job_tracker.cancel_job(&job_id);

    Ok(Json(CancelJobResponse { job_id, cancelled }))
}

/// GET /api/v1/ingest - List active jobs.
pub async fn list_active_jobs(
    State(state): State<Arc<AppState>>,
) -> ApiResult<Json<ActiveJobsResponse>> {
    let job_ids = state.job_tracker.list_active_jobs();

    let jobs: Vec<JobStatusResponse> = job_ids
        .iter()
        .filter_map(|job_id| {
            state.job_tracker.get_job(job_id).map(|job_state| {
                let progress = if job_state.progress.total > 0 {
                    Some(job_state.progress.clone())
                } else {
                    None
                };

                JobStatusResponse {
                    job_id: *job_id,
                    status: job_state.status,
                    progress,
                    documents_processed: job_state.documents_processed,
                    chunks_created: job_state.chunks_created,
                    started_at: job_state.started_at,
                    completed_at: job_state.completed_at,
                    duration_seconds: job_state.duration_seconds(),
                    error_message: job_state.error_message,
                    errors: job_state.errors,
                }
            })
        })
        .collect();

    let total = jobs.len();
    Ok(Json(ActiveJobsResponse { jobs, total }))
}

/// POST /api/v1/ingest/sync - Start incremental sync.
pub async fn start_sync(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SyncRequest>,
) -> ApiResult<(StatusCode, Json<SyncResponse>)> {
    let job_id = state.job_tracker.create_job(request.tenant_id.clone());

    tracing::info!(
        job_id = %job_id,
        source_type = ?request.source_type,
        tenant_id = %request.tenant_id,
        "Started sync job"
    );

    // TODO: Spawn actual sync task

    Ok((
        StatusCode::ACCEPTED,
        Json(SyncResponse {
            job_id,
            status: "queued".into(),
            estimated_completion: None,
            message: "Incremental sync job started".into(),
        }),
    ))
}

/// POST /api/v1/ingest/reembed - Start re-embedding job.
pub async fn start_reembed(
    State(state): State<Arc<AppState>>,
    Json(request): Json<ReembedRequest>,
) -> ApiResult<(StatusCode, Json<ReembedResponse>)> {
    let tenant_id = request
        .target_scope
        .tenant_id
        .clone()
        .unwrap_or_else(|| "default".into());

    let job_id = state.job_tracker.create_job(tenant_id.clone());
    let embedding_job_id = Uuid::new_v4();

    tracing::info!(
        job_id = %job_id,
        embedding_job_id = %embedding_job_id,
        model = %request.embedding_model,
        tenant_id = %tenant_id,
        "Started re-embedding job"
    );

    // TODO: Spawn actual reembed task

    Ok((
        StatusCode::ACCEPTED,
        Json(ReembedResponse {
            job_id,
            embedding_job_id,
            status: "pending".into(),
            estimated_completion: None,
            message: format!("Re-embedding job started with model {}", request.embedding_model),
        }),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::types::{ACLContext, ProcessingOptions, SourceType, Visibility};

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_start_ingestion() {
        let state = test_state();
        let request = IngestRequest {
            source_type: SourceType::Filesystem,
            source_config: serde_json::json!({"path": "/data"}),
            processing: ProcessingOptions::default(),
            acl: ACLContext {
                tenant_id: "tenant-1".into(),
                visibility: Visibility::Private,
                allowed_groups: vec![],
                allowed_users: vec![],
            },
        };

        let result = start_ingestion(State(state.clone()), Json(request)).await;
        assert!(result.is_ok());

        let (status, response) = result.unwrap();
        assert_eq!(status, StatusCode::ACCEPTED);
        assert_eq!(response.status, "pending");

        // Verify job was created
        let job_state = state.job_tracker.get_job(&response.job_id);
        assert!(job_state.is_some());
    }

    #[tokio::test]
    async fn test_get_job_status() {
        let state = test_state();
        let job_id = state.job_tracker.create_job("tenant-1".into());

        let result = get_job_status(State(state), Path(job_id)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert_eq!(response.job_id, job_id);
        assert_eq!(response.status, JobStatus::Pending);
    }

    #[tokio::test]
    async fn test_get_job_status_not_found() {
        let state = test_state();
        let fake_id = Uuid::new_v4();

        let result = get_job_status(State(state), Path(fake_id)).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_cancel_job() {
        let state = test_state();
        let job_id = state.job_tracker.create_job("tenant-1".into());

        let result = cancel_job(State(state.clone()), Path(job_id)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert!(response.cancelled);

        // Verify job was cancelled
        let job_state = state.job_tracker.get_job(&job_id).unwrap();
        assert_eq!(job_state.status, JobStatus::Revoked);
    }

    #[tokio::test]
    async fn test_list_active_jobs() {
        let state = test_state();
        let _job1 = state.job_tracker.create_job("tenant-1".into());
        let _job2 = state.job_tracker.create_job("tenant-1".into());

        let result = list_active_jobs(State(state)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert_eq!(response.total, 2);
        assert_eq!(response.jobs.len(), 2);
    }
}
```

**Step 2: Update routes/mod.rs**

Update `crates/rag-ingestion/src/api/routes/mod.rs`:

```rust
//! API route handlers for the ingestion service.

pub mod health;
pub mod ingest;

pub use health::{health, liveness, readiness};
pub use ingest::{
    cancel_job, get_job_status, ingest_single_document, list_active_jobs, start_ingestion,
    start_reembed, start_sync,
};
```

**Step 3: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion routes::ingest`
Expected: All tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/api/routes/
git commit -m "feat(rag-ingestion): add ingest route handlers"
```

---

## Task 8: Create Document Route Handlers

**Files:**
- Create: `crates/rag-ingestion/src/api/routes/documents.rs`
- Modify: `crates/rag-ingestion/src/api/routes/mod.rs`

**Step 1: Create documents.rs**

Create `crates/rag-ingestion/src/api/routes/documents.rs`:

```rust
//! Document management route handlers.

use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use uuid::Uuid;

use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{
    BatchDeleteRequest, BatchDeleteResponse, DocumentDeleteResponse, DocumentListResponse,
    DocumentResponse, DocumentSyncStatus, IndexStatusValue, IngestResponse, ReindexRequest,
    SyncStatusFilter, SyncStatusResponse, SyncStatusSummary,
};

/// Query parameters for list_documents.
#[derive(Debug, Deserialize)]
pub struct ListDocumentsQuery {
    #[serde(default = "default_page")]
    pub page: i32,
    #[serde(default = "default_page_size")]
    pub page_size: i32,
    pub source_type: Option<String>,
    pub status: Option<String>,
    pub search: Option<String>,
}

fn default_page() -> i32 { 1 }
fn default_page_size() -> i32 { 20 }

/// Query parameters for sync_status.
#[derive(Debug, Deserialize)]
pub struct SyncStatusQuery {
    #[serde(default)]
    pub status_filter: SyncStatusFilter,
    pub since: Option<DateTime<Utc>>,
    #[serde(default = "default_limit")]
    pub limit: i32,
    #[serde(default)]
    pub offset: i32,
}

fn default_limit() -> i32 { 100 }

/// GET /api/v1/documents - List documents.
pub async fn list_documents(
    State(_state): State<Arc<AppState>>,
    Query(query): Query<ListDocumentsQuery>,
) -> ApiResult<Json<DocumentListResponse>> {
    // TODO: Implement actual database query
    // For now, return empty list

    let page_size = query.page_size.clamp(1, 100);

    Ok(Json(DocumentListResponse {
        documents: vec![],
        total: 0,
        page: query.page,
        page_size,
        pages: 0,
    }))
}

/// GET /api/v1/documents/sync-status - Get sync status.
pub async fn get_sync_status(
    State(_state): State<Arc<AppState>>,
    Query(query): Query<SyncStatusQuery>,
) -> ApiResult<Json<SyncStatusResponse>> {
    // TODO: Implement actual sync status query
    // For now, return empty response

    Ok(Json(SyncStatusResponse {
        summary: SyncStatusSummary::default(),
        documents: vec![],
        total: 0,
        limit: query.limit,
        offset: query.offset,
    }))
}

/// GET /api/v1/documents/{document_id} - Get document.
pub async fn get_document(
    State(_state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
) -> ApiResult<Json<DocumentResponse>> {
    // TODO: Implement actual database lookup
    // For now, return not found

    Err(ApiError::not_found(format!(
        "Document {document_id} not found"
    )))
}

/// DELETE /api/v1/documents/{document_id} - Delete document.
pub async fn delete_document(
    State(_state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
    Query(query): Query<DeleteDocumentQuery>,
) -> ApiResult<Json<DocumentDeleteResponse>> {
    // TODO: Implement actual deletion
    // For now, return not found

    let _ = query.hard_delete; // Would use this

    Err(ApiError::not_found(format!(
        "Document {document_id} not found"
    )))
}

/// Query parameters for delete_document.
#[derive(Debug, Deserialize)]
pub struct DeleteDocumentQuery {
    #[serde(default = "default_hard_delete")]
    pub hard_delete: bool,
}

fn default_hard_delete() -> bool { true }

/// POST /api/v1/documents/batch-delete - Batch delete documents.
pub async fn batch_delete_documents(
    State(_state): State<Arc<AppState>>,
    Query(query): Query<DeleteDocumentQuery>,
    Json(request): Json<BatchDeleteRequest>,
) -> ApiResult<Json<BatchDeleteResponse>> {
    // TODO: Implement actual batch deletion
    // For now, return all as not found

    let _ = query.hard_delete;

    let results: Vec<DocumentDeleteResponse> = request
        .document_ids
        .iter()
        .map(|id| DocumentDeleteResponse {
            document_id: *id,
            deleted: false,
            chunks_deleted: 0,
            message: format!("Document {} not found", id),
        })
        .collect();

    let failed_count = results.len() as i32;

    Ok(Json(BatchDeleteResponse {
        deleted_count: 0,
        failed_count,
        results,
    }))
}

/// POST /api/v1/documents/{document_id}/reindex - Reindex document.
pub async fn reindex_document(
    State(state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
    Json(_request): Json<Option<ReindexRequest>>,
) -> ApiResult<(StatusCode, Json<IngestResponse>)> {
    // TODO: Implement actual reindexing
    // For now, create a job and return

    let job_id = state.job_tracker.create_job("default".into());

    tracing::info!(
        job_id = %job_id,
        document_id = %document_id,
        "Started reindex job"
    );

    Ok((
        StatusCode::ACCEPTED,
        Json(IngestResponse {
            job_id,
            status: "pending".into(),
            message: "Reindexing started".into(),
            created_at: Utc::now(),
        }),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::jobs::JobTracker;

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_list_documents_empty() {
        let state = test_state();
        let query = ListDocumentsQuery {
            page: 1,
            page_size: 20,
            source_type: None,
            status: None,
            search: None,
        };

        let result = list_documents(State(state), Query(query)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert_eq!(response.total, 0);
        assert!(response.documents.is_empty());
    }

    #[tokio::test]
    async fn test_get_document_not_found() {
        let state = test_state();
        let doc_id = Uuid::new_v4();

        let result = get_document(State(state), Path(doc_id)).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_reindex_document() {
        let state = test_state();
        let doc_id = Uuid::new_v4();

        let result = reindex_document(State(state), Path(doc_id), Json(None)).await;
        assert!(result.is_ok());

        let (status, response) = result.unwrap();
        assert_eq!(status, StatusCode::ACCEPTED);
        assert_eq!(response.status, "pending");
    }

    #[tokio::test]
    async fn test_batch_delete_not_found() {
        let state = test_state();
        let request = BatchDeleteRequest {
            document_ids: vec![Uuid::new_v4(), Uuid::new_v4()],
        };
        let query = DeleteDocumentQuery { hard_delete: true };

        let result = batch_delete_documents(State(state), Query(query), Json(request)).await;
        assert!(result.is_ok());

        let response = result.unwrap();
        assert_eq!(response.deleted_count, 0);
        assert_eq!(response.failed_count, 2);
    }
}
```

**Step 2: Update routes/mod.rs**

Update `crates/rag-ingestion/src/api/routes/mod.rs`:

```rust
//! API route handlers for the ingestion service.

pub mod documents;
pub mod health;
pub mod ingest;

pub use documents::{
    batch_delete_documents, delete_document, get_document, get_sync_status, list_documents,
    reindex_document,
};
pub use health::{health, liveness, readiness};
pub use ingest::{
    cancel_job, get_job_status, ingest_single_document, list_active_jobs, start_ingestion,
    start_reembed, start_sync,
};
```

**Step 3: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion routes::documents`
Expected: All tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/api/routes/
git commit -m "feat(rag-ingestion): add document route handlers"
```

---

## Task 9: Create Server and Router

**Files:**
- Create: `crates/rag-ingestion/src/api/server.rs`
- Modify: `crates/rag-ingestion/src/api/mod.rs`

**Step 1: Create server.rs**

Create `crates/rag-ingestion/src/api/server.rs`:

```rust
//! Server setup and configuration for the ingestion service.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    routing::{delete, get, post},
    Router,
};
use tower::ServiceBuilder;
use tower_http::{
    cors::{Any, CorsLayer},
    timeout::TimeoutLayer,
    trace::{DefaultMakeSpan, DefaultOnRequest, DefaultOnResponse, TraceLayer},
};
use tracing::Level;

use crate::api::routes;
use crate::api::state::AppState;

/// Default request timeout in seconds.
const DEFAULT_TIMEOUT_SECS: u64 = 60;

/// Create the Axum router with all routes configured.
#[must_use]
pub fn create_router(state: Arc<AppState>) -> Router {
    create_router_with_timeout(state, DEFAULT_TIMEOUT_SECS)
}

/// Create the Axum router with a custom timeout.
#[must_use]
pub fn create_router_with_timeout(state: Arc<AppState>, timeout_secs: u64) -> Router {
    // Build middleware stack
    let middleware = ServiceBuilder::new()
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(DefaultMakeSpan::new().level(Level::INFO))
                .on_request(DefaultOnRequest::new().level(Level::INFO))
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        )
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .layer(TimeoutLayer::new(Duration::from_secs(timeout_secs)));

    // Build the router
    Router::new()
        // Ingest routes
        .route("/api/v1/ingest", post(routes::start_ingestion))
        .route("/api/v1/ingest", get(routes::list_active_jobs))
        .route("/api/v1/ingest/single", post(routes::ingest_single_document))
        .route("/api/v1/ingest/sync", post(routes::start_sync))
        .route("/api/v1/ingest/reembed", post(routes::start_reembed))
        .route("/api/v1/ingest/:job_id", get(routes::get_job_status))
        .route("/api/v1/ingest/:job_id", delete(routes::cancel_job))
        // Document routes
        .route("/api/v1/documents", get(routes::list_documents))
        .route("/api/v1/documents/sync-status", get(routes::get_sync_status))
        .route("/api/v1/documents/batch-delete", post(routes::batch_delete_documents))
        .route("/api/v1/documents/:document_id", get(routes::get_document))
        .route("/api/v1/documents/:document_id", delete(routes::delete_document))
        .route("/api/v1/documents/:document_id/reindex", post(routes::reindex_document))
        // Health routes
        .route("/health", get(routes::health))
        .route("/health/live", get(routes::liveness))
        .route("/health/ready", get(routes::readiness))
        // Apply middleware
        .layer(middleware)
        // Add shared state
        .with_state(state)
}

/// Run the HTTP server.
pub async fn run_server(state: Arc<AppState>, addr: SocketAddr) -> Result<(), ServerError> {
    run_server_with_timeout(state, addr, DEFAULT_TIMEOUT_SECS).await
}

/// Run the HTTP server with a custom timeout.
pub async fn run_server_with_timeout(
    state: Arc<AppState>,
    addr: SocketAddr,
    timeout_secs: u64,
) -> Result<(), ServerError> {
    let app = create_router_with_timeout(state, timeout_secs);

    tracing::info!("Starting ingestion server on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .await
        .map_err(ServerError::Serve)?;

    Ok(())
}

/// Run the HTTP server with graceful shutdown.
pub async fn run_server_with_shutdown<F>(
    state: Arc<AppState>,
    addr: SocketAddr,
    shutdown_signal: F,
) -> Result<(), ServerError>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let app = create_router(state);

    tracing::info!("Starting ingestion server on {} with graceful shutdown", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal)
        .await
        .map_err(ServerError::Serve)?;

    tracing::info!("Server shut down gracefully");

    Ok(())
}

/// Server configuration.
#[derive(Debug, Clone)]
pub struct ServerConfig {
    /// Address to bind to.
    pub addr: SocketAddr,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
    /// Enable CORS for all origins.
    pub cors_enabled: bool,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            addr: "0.0.0.0:8001".parse().unwrap(),
            timeout_secs: DEFAULT_TIMEOUT_SECS,
            cors_enabled: true,
        }
    }
}

impl ServerConfig {
    /// Create a new server config with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the bind address.
    #[must_use]
    pub fn with_addr(mut self, addr: SocketAddr) -> Self {
        self.addr = addr;
        self
    }

    /// Set the request timeout.
    #[must_use]
    pub const fn with_timeout(mut self, timeout_secs: u64) -> Self {
        self.timeout_secs = timeout_secs;
        self
    }

    /// Load configuration from environment variables.
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        let host = std::env::var("INGESTION_HOST").unwrap_or_else(|_| "0.0.0.0".into());
        let port = std::env::var("INGESTION_PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8001);

        if let Ok(addr) = format!("{host}:{port}").parse() {
            config.addr = addr;
        }

        if let Ok(timeout) = std::env::var("INGESTION_TIMEOUT_SECS") {
            if let Ok(secs) = timeout.parse() {
                config.timeout_secs = secs;
            }
        }

        config
    }
}

/// Server error types.
#[derive(Debug)]
pub enum ServerError {
    /// Failed to bind to address.
    Bind(std::io::Error),
    /// Server error during operation.
    Serve(std::io::Error),
}

impl std::fmt::Display for ServerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Bind(e) => write!(f, "Failed to bind to address: {e}"),
            Self::Serve(e) => write!(f, "Server error: {e}"),
        }
    }
}

impl std::error::Error for ServerError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Bind(e) | Self::Serve(e) => Some(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::jobs::JobTracker;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_router_health_live() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/health/live")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_router_health_ready() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/health/ready")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_router_list_documents() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/documents")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_router_list_active_jobs() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/ingest")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[test]
    fn test_server_config_default() {
        let config = ServerConfig::default();
        assert_eq!(config.addr.port(), 8001);
        assert_eq!(config.timeout_secs, 60);
    }

    #[test]
    fn test_server_config_builder() {
        let addr: SocketAddr = "127.0.0.1:9000".parse().unwrap();
        let config = ServerConfig::new().with_addr(addr).with_timeout(120);

        assert_eq!(config.addr.port(), 9000);
        assert_eq!(config.timeout_secs, 120);
    }
}
```

**Step 2: Update api/mod.rs**

Update `crates/rag-ingestion/src/api/mod.rs`:

```rust
//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.
//!
//! # Routes
//!
//! ## Ingest Routes (`/api/v1/ingest`)
//!
//! - `POST /api/v1/ingest` - Start batch ingestion job
//! - `GET /api/v1/ingest` - List active jobs
//! - `POST /api/v1/ingest/single` - Ingest single document
//! - `POST /api/v1/ingest/sync` - Start incremental sync
//! - `POST /api/v1/ingest/reembed` - Start re-embedding job
//! - `GET /api/v1/ingest/{job_id}` - Get job status
//! - `DELETE /api/v1/ingest/{job_id}` - Cancel job
//!
//! ## Document Routes (`/api/v1/documents`)
//!
//! - `GET /api/v1/documents` - List documents
//! - `GET /api/v1/documents/sync-status` - Get sync status
//! - `GET /api/v1/documents/{document_id}` - Get document
//! - `DELETE /api/v1/documents/{document_id}` - Delete document
//! - `POST /api/v1/documents/{document_id}/reindex` - Reindex document
//! - `POST /api/v1/documents/batch-delete` - Batch delete
//!
//! ## Health Routes
//!
//! - `GET /health` - Full health check
//! - `GET /health/live` - Liveness probe
//! - `GET /health/ready` - Readiness probe

pub mod error;
pub mod jobs;
pub mod routes;
pub mod server;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use server::{create_router, run_server, run_server_with_shutdown, ServerConfig, ServerError};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::*;
```

**Step 3: Run all tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/api/
git commit -m "feat(rag-ingestion): add server and router configuration"
```

---

## Task 10: Create Binary Entry Point

**Files:**
- Create: `crates/rag-ingestion/src/bin/ingestion-api.rs`
- Modify: `crates/rag-ingestion/Cargo.toml`

**Step 1: Add binary target to Cargo.toml**

Add to `crates/rag-ingestion/Cargo.toml`:

```toml
[[bin]]
name = "ingestion-api"
path = "src/bin/ingestion-api.rs"
```

**Step 2: Create binary entry point**

Create `crates/rag-ingestion/src/bin/ingestion-api.rs`:

```rust
//! Ingestion API service binary.
//!
//! This is the entry point for the ingestion HTTP server.
//!
//! # Usage
//!
//! ```bash
//! # Run with default settings (0.0.0.0:8001)
//! cargo run --bin ingestion-api
//!
//! # Configure via environment variables
//! INGESTION_HOST=127.0.0.1 INGESTION_PORT=9001 cargo run --bin ingestion-api
//! ```

use std::sync::Arc;

use rag_ingestion::api::{
    run_server_with_shutdown, AppState, JobTracker, ServerConfig,
};
use tokio::signal;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ingestion_api=info,rag_ingestion=info,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Load configuration
    let config = ServerConfig::from_env();

    tracing::info!(
        addr = %config.addr,
        timeout_secs = config.timeout_secs,
        "Starting ingestion API server"
    );

    // Build application state
    let state = Arc::new(
        AppState::builder()
            .job_tracker(Arc::new(JobTracker::new()))
            // TODO: Add index_coordinator and embedding_client when available
            .build()?,
    );

    // Run server with graceful shutdown
    run_server_with_shutdown(state, config.addr, shutdown_signal()).await?;

    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }

    tracing::info!("Shutdown signal received, starting graceful shutdown");
}
```

**Step 3: Add tracing-subscriber to dev-dependencies**

Update `crates/rag-ingestion/Cargo.toml` to add:

```toml
[dependencies]
# ... existing deps ...
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
```

**Step 4: Verify it compiles**

Run: `cd crates && cargo build -p rag-ingestion --bin ingestion-api`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add crates/rag-ingestion/Cargo.toml crates/rag-ingestion/src/bin/
git commit -m "feat(rag-ingestion): add ingestion-api binary entry point"
```

---

## Task 11: Run All Tests and Final Verification

**Step 1: Run all rag-ingestion tests**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 2: Run clippy**

Run: `cd crates && cargo clippy -p rag-ingestion -- -D warnings`
Expected: No warnings

**Step 3: Check formatting**

Run: `cd crates && cargo fmt -p rag-ingestion -- --check`
Expected: No formatting issues

**Step 4: Build in release mode**

Run: `cd crates && cargo build -p rag-ingestion --release`
Expected: Build succeeds

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(rag-ingestion): complete P4.6 Ingestion API implementation

Implements Rust ingestion API mirroring Python FastAPI service:

- Ingest routes: start_ingestion, single_document, sync, reembed, job status/cancel
- Document routes: list, get, delete, batch_delete, reindex, sync_status
- Health routes: liveness, readiness, full health check
- In-memory job tracker with DashMap and CancellationToken
- AppState with builder pattern
- Comprehensive test coverage

Closes Phase 4.6 of Rust migration plan."
```

---

## Summary

This implementation plan creates the complete Ingestion API in Rust:

| Task | Description | Files Created/Modified |
|------|-------------|------------------------|
| 1 | Add dependencies | Cargo.toml |
| 2 | Error types | api/error.rs, api/mod.rs |
| 3 | Request/response types | api/types.rs |
| 4 | Job tracker | api/jobs.rs |
| 5 | AppState | api/state.rs |
| 6 | Health routes | api/routes/health.rs |
| 7 | Ingest routes | api/routes/ingest.rs |
| 8 | Document routes | api/routes/documents.rs |
| 9 | Server/router | api/server.rs |
| 10 | Binary entry point | bin/ingestion-api.rs |
| 11 | Final verification | - |

**Total estimated effort:** 1-2 weeks

**Next steps after completion:**
1. Integrate with actual `IndexCoordinator` for document storage
2. Integrate with `EmbeddingClient` for vector generation
3. Add actual background job processing in route handlers
4. Add authentication middleware (JWT validation)
5. Deploy alongside Python service in shadow mode
