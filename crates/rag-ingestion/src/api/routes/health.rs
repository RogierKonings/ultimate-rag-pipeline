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
pub async fn readiness(State(state): State<Arc<AppState>>) -> ApiResult<Json<ReadinessResponse>> {
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
