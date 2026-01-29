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
