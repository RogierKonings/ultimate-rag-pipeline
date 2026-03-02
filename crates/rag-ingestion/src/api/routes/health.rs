//! Health check endpoints for the ingestion service.

use std::sync::Arc;

use axum::{extract::State, Json};

use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{HealthResponse, LivenessResponse, ReadinessResponse};

/// Handle the GET /health/live endpoint (Kubernetes liveness probe).
pub async fn liveness() -> Json<LivenessResponse> {
    Json(LivenessResponse::default())
}

/// Handle the GET /health/ready endpoint (Kubernetes readiness probe).
///
/// Probes `PostgreSQL` and Redis connectivity to ensure the service can process requests.
/// Returns 503 Service Unavailable when critical dependencies are down.
pub async fn readiness(State(state): State<Arc<AppState>>) -> ApiResult<Json<ReadinessResponse>> {
    let has_coordinator = state.has_index_coordinator();
    let has_embedding = state.has_embedding_client();

    // Probe PostgreSQL if a database pool is configured
    let db_healthy = if let Some(ref db) = state.database {
        match tokio::time::timeout(std::time::Duration::from_secs(3), db.ping()).await {
            Ok(Ok(())) => true,
            Ok(Err(e)) => {
                tracing::warn!(error = %e, "Database readiness probe failed");
                false
            }
            Err(_) => {
                tracing::warn!("Database readiness probe timed out");
                false
            }
        }
    } else {
        // No database configured — treat as not ready since it is a critical dependency
        false
    };

    // Probe Redis if a job queue is configured
    let redis_healthy = if let Some(ref queue) = state.job_queue {
        match tokio::time::timeout(std::time::Duration::from_secs(2), queue.ping()).await {
            Ok(Ok(())) => true,
            Ok(Err(e)) => {
                tracing::warn!(error = %e, "Redis readiness probe failed");
                false
            }
            Err(_) => {
                tracing::warn!("Redis readiness probe timed out");
                false
            }
        }
    } else {
        // No queue configured — not critical for readiness, allow degraded operation
        true
    };

    // Service is ready if the database is reachable (critical dependency)
    let ready = db_healthy;

    if !ready {
        return Err(ApiError::service_unavailable(
            "Service not ready: database unreachable",
        ));
    }

    let degradation_mode = if has_coordinator && has_embedding && redis_healthy {
        None
    } else if !has_coordinator && !has_embedding {
        Some("minimal".into())
    } else if !redis_healthy {
        Some("no_queue".into())
    } else if !has_coordinator {
        Some("no_indexing".into())
    } else if !has_embedding {
        Some("no_embedding".into())
    } else {
        None
    };

    Ok(Json(ReadinessResponse {
        status: "ready".into(),
        degradation_mode,
    }))
}

/// Handle the GET /health endpoint (full health check).
pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let has_coordinator = state.has_index_coordinator();
    let has_embedding = state.has_embedding_client();

    let status = if has_coordinator && has_embedding {
        "healthy"
    } else {
        "degraded"
    };

    let resp = HealthResponse {
        status: status.to_string(),
        version: state.version().to_string(),
        ..if status == "healthy" {
            HealthResponse::healthy(state.version())
        } else {
            HealthResponse::degraded(state.version())
        }
    }
    .with_component("job_tracker", true)
    .with_component("index_coordinator", has_coordinator)
    .with_component("embedding_client", has_embedding);

    Json(resp)
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
    async fn test_readiness_no_database_returns_unavailable() {
        let state = test_state();
        let result = readiness(State(state)).await;
        // Without a database, the service should report not ready (503)
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_health() {
        let state = test_state();
        let response = health(State(state)).await;

        assert_eq!(response.status, "degraded");
        assert!(response.components.contains_key("job_tracker"));
        assert!(response.components["job_tracker"]);
    }
}
