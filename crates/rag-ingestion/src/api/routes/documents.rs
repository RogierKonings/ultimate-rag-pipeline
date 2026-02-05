//! Document management route handlers.

use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use rag_database::DocumentRepository;
use serde::Deserialize;
use uuid::Uuid;

use crate::api::error::{ApiError, ApiResult};
#[cfg(test)]
use crate::api::jobs::JobTracker;
use crate::api::state::AppState;
use crate::api::types::{
    BatchDeleteRequest, BatchDeleteResponse, DocumentDeleteResponse, DocumentListResponse,
    DocumentResponse, IngestResponse, ReindexRequest, SyncStatusFilter, SyncStatusResponse,
    SyncStatusSummary,
};

/// Query parameters for list_documents.
#[derive(Debug, Deserialize)]
pub struct ListDocumentsQuery {
    /// Tenant ID for multi-tenancy (required).
    pub tenant_id: String,
    #[serde(default = "default_page")]
    pub page: i32,
    #[serde(default = "default_page_size")]
    pub page_size: i32,
    pub source_type: Option<String>,
    pub status: Option<String>,
    pub search: Option<String>,
}

fn default_page() -> i32 {
    1
}
fn default_page_size() -> i32 {
    20
}

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

fn default_limit() -> i32 {
    100
}

/// GET /api/v1/documents - List documents.
pub async fn list_documents(
    State(state): State<Arc<AppState>>,
    Query(query): Query<ListDocumentsQuery>,
) -> ApiResult<Json<DocumentListResponse>> {
    let page_size = query.page_size.clamp(1, 100);
    let page = query.page.max(1);
    let offset = (page - 1) * page_size;

    // Check if database is available
    let database = state.database.as_ref().ok_or_else(|| {
        ApiError::internal("Database not configured")
    })?;

    let repo = DocumentRepository::new(database.inner().clone());

    // Get total count for pagination
    let total = repo
        .count(&query.tenant_id)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to count documents: {e}")))?;

    // Get documents for this page
    let documents = repo
        .list(&query.tenant_id, i64::from(page_size), i64::from(offset))
        .await
        .map_err(|e| ApiError::internal(format!("Failed to list documents: {e}")))?;

    // Convert to response format
    let document_responses: Vec<DocumentResponse> = documents
        .into_iter()
        .map(|doc| DocumentResponse {
            document_id: doc.id,
            source_id: doc.source_uri.clone(),
            source_type: doc.source_type.clone(),
            filename: doc.title.clone(),
            mime_type: doc.mime_type.clone(),
            title: doc.title,
            author: None,
            chunk_count: doc.chunk_count,
            total_tokens: 0, // Not tracked in current schema
            tenant_id: doc.tenant_id,
            visibility: format!("{:?}", doc.visibility).to_lowercase(),
            created_at: doc.created_at,
            updated_at: doc.updated_at,
            indexed_at: None, // Could be tracked separately
            status: doc.status,
        })
        .collect();

    let pages = if total == 0 {
        0
    } else {
        ((total as i32) + page_size - 1) / page_size
    };

    tracing::debug!(
        tenant_id = %query.tenant_id,
        total = total,
        page = page,
        page_size = page_size,
        returned = document_responses.len(),
        "Listed documents"
    );

    Ok(Json(DocumentListResponse {
        documents: document_responses,
        total,
        page,
        page_size,
        pages,
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

fn default_hard_delete() -> bool {
    true
}

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

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_list_documents_no_database() {
        // Without database configured, should return an error
        let state = test_state();
        let query = ListDocumentsQuery {
            tenant_id: "test-tenant".to_string(),
            page: 1,
            page_size: 20,
            source_type: None,
            status: None,
            search: None,
        };

        let result = list_documents(State(state), Query(query)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
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
