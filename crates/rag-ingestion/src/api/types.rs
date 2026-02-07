//! Request and response types for the ingestion API.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ============================================================================
// Enums
// ============================================================================

pub use rag_types::{ChunkingStrategy, SourceType, Visibility};

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

fn default_chunk_size() -> u32 {
    512
}
fn default_chunk_overlap() -> u32 {
    50
}
fn default_pii_detection() -> bool {
    true
}

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
#[derive(Debug, Clone, Serialize, Deserialize)]
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

fn default_batch_size() -> u32 {
    100
}

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
// Health Types (re-exported from rag-types)
// ============================================================================

pub use rag_types::{
    ComponentHealth, HealthResponse, LivenessResponse, ReadinessResponse,
};

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
}
