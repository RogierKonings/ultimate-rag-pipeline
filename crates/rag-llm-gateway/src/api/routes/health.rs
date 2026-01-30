//! Health check endpoints.

use std::sync::Arc;

use axum::{extract::State, Json};
use serde::Serialize;

use crate::api::AppState;
use crate::metrics;

/// Service information response.
#[derive(Debug, Serialize)]
pub struct ServiceInfo {
    /// Service name.
    service: &'static str,
    /// Service version.
    version: &'static str,
    /// Service status.
    status: &'static str,
}

/// Root endpoint handler.
///
/// Returns basic service information.
pub async fn root() -> Json<ServiceInfo> {
    Json(ServiceInfo {
        service: "llm-gateway",
        version: env!("CARGO_PKG_VERSION"),
        status: "running",
    })
}

/// Health check response.
#[derive(Debug, Serialize)]
pub struct HealthResponse {
    /// Overall status.
    status: &'static str,
    /// Individual service health.
    services: ServicesHealth,
}

/// Individual services health status.
#[derive(Debug, Serialize)]
pub struct ServicesHealth {
    /// Embedding service status.
    embedding: &'static str,
    /// Reranker service status.
    reranker: &'static str,
    /// vLLM service status.
    vllm: &'static str,
}

/// Health check endpoint.
///
/// Returns overall health and status of individual services.
pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let embedding_status = if state.embedding_model.is_some() {
        "healthy"
    } else {
        "disabled"
    };

    let reranker_status = if state.reranker_model.is_some() {
        "healthy"
    } else {
        "disabled"
    };

    let vllm_status = match &state.vllm_client {
        Some(client) => {
            if client.health_check().await {
                "healthy"
            } else {
                "unhealthy"
            }
        }
        None => "disabled",
    };

    Json(HealthResponse {
        status: "healthy",
        services: ServicesHealth {
            embedding: embedding_status,
            reranker: reranker_status,
            vllm: vllm_status,
        },
    })
}

/// Liveness probe response.
#[derive(Debug, Serialize)]
pub struct LivenessResponse {
    /// Status (always "ok" if service is running).
    status: &'static str,
}

/// Liveness probe endpoint.
///
/// Returns OK if the service is running (for Kubernetes liveness probes).
pub async fn liveness() -> Json<LivenessResponse> {
    Json(LivenessResponse { status: "ok" })
}

/// Readiness probe endpoint.
///
/// Returns OK if the service is ready to accept requests (for Kubernetes readiness probes).
pub async fn readiness(State(state): State<Arc<AppState>>) -> Json<LivenessResponse> {
    // For now, we consider the service ready if it's running.
    // In the future, we might check if models are loaded, connections are established, etc.
    let _ = state;
    Json(LivenessResponse { status: "ready" })
}

/// Prometheus metrics endpoint.
///
/// Returns metrics in Prometheus text format.
pub async fn metrics() -> String {
    metrics::gather_metrics()
}
