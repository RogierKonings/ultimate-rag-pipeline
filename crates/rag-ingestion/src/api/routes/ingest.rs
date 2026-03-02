//! Ingestion job route handlers.

use std::sync::Arc;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use chrono::Utc;
use serde_json::json;
use uuid::Uuid;

use crate::api::error::{ApiError, ApiResult};
#[cfg(test)]
use crate::api::jobs::JobTracker;
use crate::api::state::AppState;
use crate::api::types::{
    ActiveJobsResponse, CancelJobResponse, IngestRequest, IngestResponse, JobProgress, JobStatus,
    JobStatusResponse, ReembedRequest, ReembedResponse, SingleIngestRequest, SyncRequest,
    SyncResponse,
};
use crate::worker::{Job, JobPriority};

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

    // Enqueue job to Redis for async processing
    if let Some(job_queue) = &state.job_queue {
        let worker_job = Job::new(
            "ingest_batch",
            &request.acl.tenant_id,
            json!({
                "tracker_job_id": job_id.to_string(),
                "source_type": request.source_type,
                "source_config": request.source_config,
                "processing": {
                    "chunking_strategy": request.processing.chunking_strategy,
                    "chunk_size": request.processing.chunk_size,
                    "chunk_overlap": request.processing.chunk_overlap,
                    "enable_pii_detection": request.processing.enable_pii_detection,
                    "custom_metadata": request.processing.custom_metadata
                },
                "acl": {
                    "tenant_id": request.acl.tenant_id,
                    "visibility": request.acl.visibility,
                    "allowed_groups": request.acl.allowed_groups,
                    "allowed_users": request.acl.allowed_users
                }
            }),
        )
        .with_priority(JobPriority::Normal)
        .with_metadata("tracker_job_id", json!(job_id.to_string()));

        if let Err(e) = job_queue.enqueue(&worker_job).await {
            tracing::error!(error = %e, job_id = %job_id, "Failed to enqueue job to Redis");
            state
                .job_tracker
                .fail_job(&job_id, format!("Failed to enqueue: {e}"));
            return Err(ApiError::internal(format!("Failed to queue job: {e}")));
        }

        tracing::info!(
            job_id = %job_id,
            worker_job_id = %worker_job.id,
            "Job enqueued to Redis"
        );
    } else {
        tracing::warn!(job_id = %job_id, "No job queue configured - job will remain pending");
    }

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

    // Enqueue job to Redis for async processing
    if let Some(job_queue) = &state.job_queue {
        let worker_job = Job::new(
            "ingest_single",
            &request.acl.tenant_id,
            json!({
                "tracker_job_id": job_id.to_string(),
                "source_type": request.source_type,
                "source_id": request.source_id,
                "source_config": request.source_config,
                "processing": {
                    "chunking_strategy": request.processing.chunking_strategy,
                    "chunk_size": request.processing.chunk_size,
                    "chunk_overlap": request.processing.chunk_overlap,
                    "enable_pii_detection": request.processing.enable_pii_detection,
                    "custom_metadata": request.processing.custom_metadata
                },
                "acl": {
                    "tenant_id": request.acl.tenant_id,
                    "visibility": request.acl.visibility,
                    "allowed_groups": request.acl.allowed_groups,
                    "allowed_users": request.acl.allowed_users
                }
            }),
        )
        .with_priority(JobPriority::Normal)
        .with_metadata("tracker_job_id", json!(job_id.to_string()));

        if let Err(e) = job_queue.enqueue(&worker_job).await {
            tracing::error!(error = %e, job_id = %job_id, "Failed to enqueue job to Redis");
            state
                .job_tracker
                .fail_job(&job_id, format!("Failed to enqueue: {e}"));
            return Err(ApiError::internal(format!("Failed to queue job: {e}")));
        }

        tracing::info!(
            job_id = %job_id,
            worker_job_id = %worker_job.id,
            "Job enqueued to Redis"
        );
    } else {
        tracing::warn!(job_id = %job_id, "No job queue configured - job will remain pending");
    }

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

/// GET /`api/v1/ingest/{job_id`} - Get job status.
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

/// DELETE /`api/v1/ingest/{job_id`} - Cancel a job.
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
///
/// Creates a tracked job and enqueues a `sync` task to Redis for background
/// processing. The worker will compare the source against the current index
/// and only re-ingest changed or new documents.
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

    // Enqueue sync job to Redis for async processing
    if let Some(job_queue) = &state.job_queue {
        let worker_job = Job::new(
            "sync",
            &request.tenant_id,
            json!({
                "tracker_job_id": job_id.to_string(),
                "tenant_id": request.tenant_id,
                "source_type": request.source_type,
                "source_config": request.source_config,
            }),
        )
        .with_priority(JobPriority::Normal)
        .with_metadata("tracker_job_id", json!(job_id.to_string()));

        if let Err(e) = job_queue.enqueue(&worker_job).await {
            tracing::error!(error = %e, job_id = %job_id, "Failed to enqueue sync job to Redis");
            state
                .job_tracker
                .fail_job(&job_id, format!("Failed to enqueue: {e}"));
            return Err(ApiError::internal(format!("Failed to queue sync job: {e}")));
        }

        tracing::info!(
            job_id = %job_id,
            worker_job_id = %worker_job.id,
            "Sync job enqueued to Redis"
        );
    } else {
        tracing::warn!(job_id = %job_id, "No job queue configured - sync job will remain pending");
    }

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
///
/// Creates a tracked job and enqueues a `reembed` task to Redis for background
/// processing. The worker will re-generate embeddings for chunks matching the
/// target scope using the specified embedding model, then upsert the new
/// vectors into Qdrant.
pub async fn start_reembed(
    State(state): State<Arc<AppState>>,
    Json(request): Json<ReembedRequest>,
) -> ApiResult<(StatusCode, Json<ReembedResponse>)> {
    let tenant_id = request.target_scope.tenant_id.clone();
    if tenant_id.is_empty() {
        return Err(ApiError::bad_request(
            "target_scope.tenant_id must not be empty",
        ));
    }

    let job_id = state.job_tracker.create_job(tenant_id.clone());
    let embedding_job_id = Uuid::new_v4();

    tracing::info!(
        job_id = %job_id,
        embedding_job_id = %embedding_job_id,
        model = %request.embedding_model,
        tenant_id = %tenant_id,
        "Started re-embedding job"
    );

    // Enqueue reembed job to Redis for async processing
    if let Some(job_queue) = &state.job_queue {
        let worker_job = Job::new(
            "reembed",
            &tenant_id,
            json!({
                "tracker_job_id": job_id.to_string(),
                "embedding_job_id": embedding_job_id.to_string(),
                "embedding_model": request.embedding_model,
                "batch_size": request.batch_size,
                "target_scope": {
                    "tenant_id": request.target_scope.tenant_id,
                    "source_types": request.target_scope.source_types,
                    "document_ids": request.target_scope.document_ids,
                }
            }),
        )
        .with_priority(JobPriority::Normal)
        .with_metadata("tracker_job_id", json!(job_id.to_string()))
        .with_metadata("embedding_job_id", json!(embedding_job_id.to_string()));

        if let Err(e) = job_queue.enqueue(&worker_job).await {
            tracing::error!(error = %e, job_id = %job_id, "Failed to enqueue reembed job to Redis");
            state
                .job_tracker
                .fail_job(&job_id, format!("Failed to enqueue: {e}"));
            return Err(ApiError::internal(format!(
                "Failed to queue reembed job: {e}"
            )));
        }

        tracing::info!(
            job_id = %job_id,
            worker_job_id = %worker_job.id,
            embedding_job_id = %embedding_job_id,
            "Reembed job enqueued to Redis"
        );
    } else {
        tracing::warn!(
            job_id = %job_id,
            "No job queue configured - reembed job will remain pending"
        );
    }

    Ok((
        StatusCode::ACCEPTED,
        Json(ReembedResponse {
            job_id,
            embedding_job_id,
            status: "pending".into(),
            estimated_completion: None,
            message: format!(
                "Re-embedding job started with model {}",
                request.embedding_model
            ),
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
