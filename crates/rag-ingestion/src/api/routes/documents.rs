//! Document management route handlers.

use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use rag_database::{ChunkRepository, DocumentRepository};
use rag_types::{DocumentId, TenantId};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

use crate::api::error::{ApiError, ApiResult};
#[cfg(test)]
use crate::api::jobs::JobTracker;
use crate::api::state::AppState;
use crate::api::types::{
    BatchDeleteRequest, BatchDeleteResponse, DocumentDeleteResponse, DocumentListResponse,
    DocumentResponse, DocumentSyncStatus, IndexStatusValue, IngestResponse, ReindexRequest,
    SyncStatusFilter, SyncStatusResponse, SyncStatusSummary,
};
use crate::worker::{Job, JobPriority};

/// Query parameters for `list_documents`.
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

/// Query parameters for `sync_status`.
#[derive(Debug, Deserialize)]
pub struct SyncStatusQuery {
    /// Tenant ID for multi-tenancy (required).
    pub tenant_id: String,
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

/// Query parameters for `get_document`.
#[derive(Debug, Deserialize)]
pub struct GetDocumentQuery {
    /// Tenant ID for multi-tenancy (required).
    pub tenant_id: String,
}

/// Query parameters for `reindex_document`.
#[derive(Debug, Deserialize)]
pub struct ReindexQuery {
    /// Tenant ID for multi-tenancy (required).
    pub tenant_id: String,
}

/// Convert a `SourceDocument` to a `DocumentResponse`.
fn document_to_response(doc: rag_database::SourceDocument) -> DocumentResponse {
    // Extract clean filename from source_uri
    // source_uri format: uploads/{tenant_id}/{timestamp}-{filename}
    let filename = doc.source_uri.rsplit('/').next().map(|name| {
        // Remove timestamp prefix (digits followed by dash)
        if let Some(dash_pos) = name.find('-') {
            let prefix = &name[..dash_pos];
            if prefix.chars().all(|c| c.is_ascii_digit()) {
                return name[dash_pos + 1..].to_string();
            }
        }
        name.to_string()
    });

    DocumentResponse {
        document_id: doc.id,
        source_id: doc.source_uri.clone(),
        source_type: doc.source_type.clone(),
        filename,
        mime_type: doc.mime_type.clone(),
        title: doc.title.filter(|t| t != &doc.source_uri),
        author: None,
        chunk_count: doc.chunk_count,
        total_tokens: 0, // Not tracked in current schema
        tenant_id: doc.tenant_id,
        visibility: format!("{:?}", doc.visibility).to_lowercase(),
        created_at: doc.created_at,
        updated_at: doc.updated_at,
        indexed_at: None, // Could be tracked separately
        status: doc.status,
    }
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
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

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
    let document_responses: Vec<DocumentResponse> =
        documents.into_iter().map(document_to_response).collect();

    #[allow(clippy::cast_possible_truncation)] // total row count fits in i32
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
///
/// Queries documents from `PostgreSQL` and derives per-document sync status
/// based on the document's processing status. A document with status
/// "completed" is considered synced to all stores; "failed" indicates an
/// indexing error; anything else is "pending".
pub async fn get_sync_status(
    State(state): State<Arc<AppState>>,
    Query(query): Query<SyncStatusQuery>,
) -> ApiResult<Json<SyncStatusResponse>> {
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

    let repo = DocumentRepository::new(database.inner().clone());

    // Count documents by status for the summary
    let all_docs = repo
        .list(
            &query.tenant_id,
            i64::from(query.limit),
            i64::from(query.offset),
        )
        .await
        .map_err(|e| ApiError::internal(format!("Failed to list documents: {e}")))?;

    let total = repo
        .count(&query.tenant_id)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to count documents: {e}")))?;

    let mut summary = SyncStatusSummary::default();
    let mut documents = Vec::new();

    for doc in all_docs {
        let (qdrant_status, opensearch_status) = match doc.status.as_str() {
            "completed" => (IndexStatusValue::Ok, IndexStatusValue::Ok),
            "failed" => (IndexStatusValue::Error, IndexStatusValue::Error),
            "pending" | "processing" => (IndexStatusValue::Pending, IndexStatusValue::Pending),
            _ => (IndexStatusValue::Stale, IndexStatusValue::Stale),
        };

        // Update summary counts
        match qdrant_status {
            IndexStatusValue::Ok => summary.ok += 1,
            IndexStatusValue::Pending => summary.pending += 1,
            IndexStatusValue::Error => summary.error += 1,
            IndexStatusValue::Stale => summary.stale += 1,
        }

        // Apply status filter
        let include = match query.status_filter {
            SyncStatusFilter::All => true,
            SyncStatusFilter::Ok => qdrant_status == IndexStatusValue::Ok,
            SyncStatusFilter::Error => qdrant_status == IndexStatusValue::Error,
            SyncStatusFilter::Pending => qdrant_status == IndexStatusValue::Pending,
            SyncStatusFilter::AnyError => {
                qdrant_status == IndexStatusValue::Error
                    || opensearch_status == IndexStatusValue::Error
            }
        };

        // Apply since filter
        let since_ok = query.since.map_or(true, |since| doc.updated_at >= since);

        if include && since_ok {
            documents.push(DocumentSyncStatus {
                document_id: doc.id,
                source_id: doc.source_uri,
                title: doc.title,
                qdrant_status,
                opensearch_status,
                last_indexed_at: if doc.status == "completed" {
                    Some(doc.updated_at)
                } else {
                    None
                },
                last_index_error: doc.error_message,
                index_attempts: 1, // Not separately tracked; default to 1
                created_at: doc.created_at,
                updated_at: doc.updated_at,
            });
        }
    }

    tracing::debug!(
        tenant_id = %query.tenant_id,
        total = total,
        returned = documents.len(),
        ok = summary.ok,
        pending = summary.pending,
        error = summary.error,
        stale = summary.stale,
        "Sync status queried"
    );

    Ok(Json(SyncStatusResponse {
        summary,
        documents,
        total,
        limit: query.limit,
        offset: query.offset,
    }))
}

/// GET /`api/v1/documents/{document_id`} - Get document by ID.
///
/// Retrieves a single document's metadata from `PostgreSQL` scoped to the
/// provided tenant.
pub async fn get_document(
    State(state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
    Query(query): Query<GetDocumentQuery>,
) -> ApiResult<Json<DocumentResponse>> {
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

    let repo = DocumentRepository::new(database.inner().clone());

    let doc = repo
        .find_by_id_and_tenant(document_id, &query.tenant_id)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to find document: {e}")))?
        .ok_or_else(|| ApiError::not_found(format!("Document {document_id} not found")))?;

    tracing::debug!(
        document_id = %document_id,
        tenant_id = %query.tenant_id,
        "Retrieved document"
    );

    Ok(Json(document_to_response(doc)))
}

/// DELETE /`api/v1/documents/{document_id`} - Delete document.
///
/// When `hard_delete` is true (the default), the document and its chunks are
/// removed from all stores: `PostgreSQL`, Qdrant, and `OpenSearch` via the index
/// coordinator. When `hard_delete` is false, only the `PostgreSQL` record is
/// removed (soft delete).
pub async fn delete_document(
    State(state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
    Query(query): Query<DeleteDocumentQuery>,
) -> ApiResult<Json<DocumentDeleteResponse>> {
    // Check if database is available
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

    let repo = DocumentRepository::new(database.inner().clone());

    // Verify document exists and belongs to tenant
    let document = repo
        .find_by_id_and_tenant(document_id, &query.tenant_id)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to find document: {e}")))?
        .ok_or_else(|| ApiError::not_found(format!("Document {document_id} not found")))?;

    if query.hard_delete {
        // Use the index coordinator to delete from all stores in parallel
        if let Some(coordinator) = &state.index_coordinator {
            let doc_id = DocumentId::from_uuid(document_id);
            let tenant_id = TenantId::parse_str(&query.tenant_id)
                .map_err(|e| ApiError::bad_request(format!("Invalid tenant_id format: {e}")))?;

            let results = coordinator
                .delete_document(doc_id, tenant_id)
                .await
                .map_err(|e| ApiError::internal(format!("Failed to delete document: {e}")))?;

            // Log per-store results
            for (store, result) in &results {
                if !result.success {
                    tracing::warn!(
                        document_id = %document_id,
                        store = %store,
                        errors = ?result.errors,
                        "Store delete had errors (best-effort)"
                    );
                }
            }
        } else {
            // No coordinator available -- fall back to database-only delete
            let chunk_repo = ChunkRepository::new(database.inner().clone());

            // Delete chunks first (FK constraint)
            chunk_repo
                .delete_by_document(document_id)
                .await
                .map_err(|e| ApiError::internal(format!("Failed to delete chunks: {e}")))?;

            repo.delete_by_tenant(document_id, &query.tenant_id)
                .await
                .map_err(|e| ApiError::internal(format!("Failed to delete document: {e}")))?;
        }
    } else {
        // Soft delete: only remove from PostgreSQL
        let deleted = repo
            .delete_by_tenant(document_id, &query.tenant_id)
            .await
            .map_err(|e| ApiError::internal(format!("Failed to delete document: {e}")))?;

        if !deleted {
            return Err(ApiError::not_found(format!(
                "Document {document_id} not found"
            )));
        }
    }

    tracing::info!(
        document_id = %document_id,
        tenant_id = %query.tenant_id,
        hard_delete = query.hard_delete,
        "Document deleted"
    );

    // Publish cache invalidation event (fire-and-forget)
    if let Some(publisher) = &state.cache_invalidation {
        publisher
            .publish_document_deleted(&query.tenant_id, &document_id.to_string())
            .await;
    }

    Ok(Json(DocumentDeleteResponse {
        document_id,
        deleted: true,
        chunks_deleted: i64::from(document.chunk_count),
        message: "Document deleted successfully".to_string(),
    }))
}

/// Query parameters for `delete_document`.
#[derive(Debug, Deserialize)]
pub struct DeleteDocumentQuery {
    /// Tenant ID for multi-tenancy (required).
    pub tenant_id: String,
    #[serde(default = "default_hard_delete")]
    pub hard_delete: bool,
}

fn default_hard_delete() -> bool {
    true
}

/// POST /api/v1/documents/batch-delete - Batch delete documents.
///
/// Deletes multiple documents. When `hard_delete` is true, each document is
/// removed from all stores via the index coordinator. Failures on individual
/// documents are captured in the per-document results rather than failing the
/// entire batch.
#[allow(clippy::too_many_lines)]
pub async fn batch_delete_documents(
    State(state): State<Arc<AppState>>,
    Query(query): Query<DeleteDocumentQuery>,
    Json(request): Json<BatchDeleteRequest>,
) -> ApiResult<Json<BatchDeleteResponse>> {
    // Check if database is available
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

    let repo = DocumentRepository::new(database.inner().clone());

    let mut results: Vec<DocumentDeleteResponse> = Vec::with_capacity(request.document_ids.len());
    let mut deleted_count = 0i32;
    let mut failed_count = 0i32;

    for document_id in &request.document_ids {
        // Try to find the document first to get chunk_count
        let document = match repo
            .find_by_id_and_tenant(*document_id, &query.tenant_id)
            .await
        {
            Ok(Some(doc)) => doc,
            Ok(None) => {
                failed_count += 1;
                results.push(DocumentDeleteResponse {
                    document_id: *document_id,
                    deleted: false,
                    chunks_deleted: 0,
                    message: format!("Document {document_id} not found"),
                });
                continue;
            }
            Err(e) => {
                failed_count += 1;
                results.push(DocumentDeleteResponse {
                    document_id: *document_id,
                    deleted: false,
                    chunks_deleted: 0,
                    message: format!("Failed to find document: {e}"),
                });
                continue;
            }
        };

        // Perform the delete
        if query.hard_delete {
            if let Some(coordinator) = &state.index_coordinator {
                let doc_id = DocumentId::from_uuid(*document_id);
                let tenant_id = match TenantId::parse_str(&query.tenant_id) {
                    Ok(tid) => tid,
                    Err(e) => {
                        failed_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: false,
                            chunks_deleted: 0,
                            message: format!("Invalid tenant_id: {e}"),
                        });
                        continue;
                    }
                };

                match coordinator.delete_document(doc_id, tenant_id).await {
                    Ok(store_results) => {
                        let any_failure = store_results.values().any(|r| !r.success);
                        if any_failure {
                            tracing::warn!(
                                document_id = %document_id,
                                "Some stores failed during batch delete (best-effort)"
                            );
                        }
                        deleted_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: true,
                            chunks_deleted: i64::from(document.chunk_count),
                            message: "Document deleted successfully".to_string(),
                        });
                    }
                    Err(e) => {
                        failed_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: false,
                            chunks_deleted: 0,
                            message: format!("Failed to delete: {e}"),
                        });
                    }
                }
            } else {
                // No coordinator -- database-only delete
                match repo.delete_by_tenant(*document_id, &query.tenant_id).await {
                    Ok(true) => {
                        deleted_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: true,
                            chunks_deleted: i64::from(document.chunk_count),
                            message: "Document deleted successfully".to_string(),
                        });
                    }
                    Ok(false) => {
                        failed_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: false,
                            chunks_deleted: 0,
                            message: format!("Document {document_id} not found"),
                        });
                    }
                    Err(e) => {
                        failed_count += 1;
                        results.push(DocumentDeleteResponse {
                            document_id: *document_id,
                            deleted: false,
                            chunks_deleted: 0,
                            message: format!("Failed to delete document: {e}"),
                        });
                    }
                }
            }
        } else {
            // Soft delete: database only
            match repo.delete_by_tenant(*document_id, &query.tenant_id).await {
                Ok(true) => {
                    deleted_count += 1;
                    results.push(DocumentDeleteResponse {
                        document_id: *document_id,
                        deleted: true,
                        chunks_deleted: i64::from(document.chunk_count),
                        message: "Document deleted successfully".to_string(),
                    });
                }
                Ok(false) => {
                    failed_count += 1;
                    results.push(DocumentDeleteResponse {
                        document_id: *document_id,
                        deleted: false,
                        chunks_deleted: 0,
                        message: format!("Document {document_id} not found"),
                    });
                }
                Err(e) => {
                    failed_count += 1;
                    results.push(DocumentDeleteResponse {
                        document_id: *document_id,
                        deleted: false,
                        chunks_deleted: 0,
                        message: format!("Failed to delete document: {e}"),
                    });
                }
            }
        }
    }

    tracing::info!(
        tenant_id = %query.tenant_id,
        hard_delete = query.hard_delete,
        deleted_count = deleted_count,
        failed_count = failed_count,
        "Batch delete completed"
    );

    // Publish cache invalidation for all successfully deleted documents (fire-and-forget)
    if let Some(publisher) = &state.cache_invalidation {
        let deleted_ids: Vec<String> = results
            .iter()
            .filter(|r| r.deleted)
            .map(|r| r.document_id.to_string())
            .collect();
        if !deleted_ids.is_empty() {
            publisher
                .publish_batch_deleted(&query.tenant_id, deleted_ids)
                .await;
        }
    }

    Ok(Json(BatchDeleteResponse {
        deleted_count,
        failed_count,
        results,
    }))
}

/// POST /`api/v1/documents/{document_id}/reindex` - Reindex document.
///
/// Verifies the document exists in `PostgreSQL`, then enqueues a reindex job
/// to Redis for background processing by the worker pool. The job re-parses
/// the document from its source, re-chunks, re-embeds, and re-indexes into
/// all stores.
pub async fn reindex_document(
    State(state): State<Arc<AppState>>,
    Path(document_id): Path<Uuid>,
    Query(query): Query<ReindexQuery>,
    Json(request): Json<Option<ReindexRequest>>,
) -> ApiResult<(StatusCode, Json<IngestResponse>)> {
    // Verify the document exists
    let database = state
        .database
        .as_ref()
        .ok_or_else(|| ApiError::internal("Database not configured"))?;

    let repo = DocumentRepository::new(database.inner().clone());

    let document = repo
        .find_by_id_and_tenant(document_id, &query.tenant_id)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to find document: {e}")))?
        .ok_or_else(|| ApiError::not_found(format!("Document {document_id} not found")))?;

    // Mark document as pending reindex
    repo.update_status(document_id, "pending", None)
        .await
        .map_err(|e| ApiError::internal(format!("Failed to update status: {e}")))?;

    let job_id = state.job_tracker.create_job(query.tenant_id.clone());

    // Enqueue a real reindex job to Redis
    if let Some(job_queue) = &state.job_queue {
        let payload = json!({
            "tracker_job_id": job_id.to_string(),
            "document_id": document_id.to_string(),
            "source_uri": document.source_uri,
            "source_type": document.source_type,
            "tenant_id": query.tenant_id,
            "chunking_strategy": request.as_ref().and_then(|r| r.chunking_strategy.clone()),
            "chunk_size": request.as_ref().and_then(|r| r.chunk_size),
            "chunk_overlap": request.as_ref().and_then(|r| r.chunk_overlap),
        });

        let worker_job = Job::new("reindex_document", &query.tenant_id, payload)
            .with_priority(JobPriority::Normal)
            .with_metadata("tracker_job_id", json!(job_id.to_string()));

        let mut queue = job_queue.lock().await;
        if let Err(e) = queue.enqueue(&worker_job).await {
            tracing::error!(error = %e, job_id = %job_id, "Failed to enqueue reindex job to Redis");
            state
                .job_tracker
                .fail_job(&job_id, format!("Failed to enqueue: {e}"));
            return Err(ApiError::internal(format!(
                "Failed to queue reindex job: {e}"
            )));
        }

        tracing::info!(
            job_id = %job_id,
            worker_job_id = %worker_job.id,
            document_id = %document_id,
            "Reindex job enqueued to Redis"
        );
    } else {
        tracing::warn!(
            job_id = %job_id,
            document_id = %document_id,
            "No job queue configured - reindex job will remain pending"
        );
    }

    // Publish cache invalidation for reindexed document (fire-and-forget)
    if let Some(publisher) = &state.cache_invalidation {
        publisher
            .publish_document_reindexed(&query.tenant_id, &document_id.to_string())
            .await;
    }

    Ok((
        StatusCode::ACCEPTED,
        Json(IngestResponse {
            job_id,
            status: "pending".into(),
            message: format!("Reindexing started for document {document_id}"),
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
    async fn test_get_document_no_database() {
        let state = test_state();
        let doc_id = Uuid::new_v4();
        let query = GetDocumentQuery {
            tenant_id: "test-tenant".to_string(),
        };

        let result = get_document(State(state), Path(doc_id), Query(query)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_get_sync_status_no_database() {
        let state = test_state();
        let query = SyncStatusQuery {
            tenant_id: "test-tenant".to_string(),
            status_filter: SyncStatusFilter::All,
            since: None,
            limit: 100,
            offset: 0,
        };

        let result = get_sync_status(State(state), Query(query)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_reindex_document_no_database() {
        let state = test_state();
        let doc_id = Uuid::new_v4();
        let query = ReindexQuery {
            tenant_id: "test-tenant".to_string(),
        };

        let result = reindex_document(State(state), Path(doc_id), Query(query), Json(None)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_batch_delete_no_database() {
        let state = test_state();
        let request = BatchDeleteRequest {
            document_ids: vec![Uuid::new_v4(), Uuid::new_v4()],
        };
        let query = DeleteDocumentQuery {
            tenant_id: "test-tenant".to_string(),
            hard_delete: true,
        };

        let result = batch_delete_documents(State(state), Query(query), Json(request)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_delete_document_no_database() {
        let state = test_state();
        let doc_id = Uuid::new_v4();
        let query = DeleteDocumentQuery {
            tenant_id: "test-tenant".to_string(),
            hard_delete: true,
        };

        let result = delete_document(State(state), Path(doc_id), Query(query)).await;
        // Should fail because database is not configured in test state
        assert!(result.is_err());
    }

    #[test]
    fn test_document_to_response_strips_timestamp_prefix() {
        use chrono::Utc;
        use rag_database::Visibility;

        let doc = rag_database::SourceDocument {
            id: Uuid::new_v4(),
            tenant_id: "test-tenant".to_string(),
            title: None,
            source_uri: "uploads/test-tenant/1234567890-report.pdf".to_string(),
            source_type: "file".to_string(),
            mime_type: Some("application/pdf".to_string()),
            content_hash: "abc123".to_string(),
            file_size: Some(1024),
            chunk_count: 5,
            status: "completed".to_string(),
            error_message: None,
            visibility: Visibility::Private,
            allowed_groups: vec![],
            metadata: serde_json::Value::Null,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };

        let resp = document_to_response(doc);
        assert_eq!(resp.filename, Some("report.pdf".to_string()));
        assert_eq!(resp.chunk_count, 5);
        assert_eq!(resp.status, "completed");
    }
}
