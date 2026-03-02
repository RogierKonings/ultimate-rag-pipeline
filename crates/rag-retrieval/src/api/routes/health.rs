//! Health check endpoints for the retrieval service.
//!
//! This module provides health endpoints for Kubernetes probes and service monitoring:
//! - `GET /health` - Full health check with component status
//! - `GET /health/live` - Kubernetes liveness probe
//! - `GET /health/ready` - Kubernetes readiness probe

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, Json};
use chrono::Utc;
use tracing::{debug, warn};

use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{ComponentHealth, HealthResponse, LivenessResponse, ReadinessResponse};

/// The service version.
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Handle the GET /health endpoint.
///
/// Returns detailed health status of all dependent components including:
/// - Qdrant (semantic search)
/// - `OpenSearch` (keyword search)
/// - Reranker (LLM Gateway)
///
/// # Response Status
///
/// - `healthy`: All components operational
/// - `degraded`: Some components down but service functional
/// - `unhealthy`: Critical components down
pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let mut components: HashMap<String, bool> = HashMap::new();
    let mut component_details: Vec<ComponentHealth> = Vec::new();

    // Check embedding service and search backends in parallel
    let (embedding_health, (qdrant_health, opensearch_health)) =
        tokio::join!(check_embedding(&state), check_search_backends(&state));
    components.insert("embedding".into(), embedding_health.healthy);
    component_details.push(embedding_health);
    components.insert("qdrant".into(), qdrant_health.healthy);
    components.insert("opensearch".into(), opensearch_health.healthy);
    component_details.push(qdrant_health);
    component_details.push(opensearch_health);

    // Check reranker if available
    if state.has_reranker() {
        let reranker_health = check_reranker(&state).await;
        components.insert("reranker".into(), reranker_health.healthy);
        component_details.push(reranker_health);
    }

    // Determine overall status
    let critical_healthy = components.get("qdrant").copied().unwrap_or(false)
        || components.get("opensearch").copied().unwrap_or(false);

    let all_healthy = components.values().all(|&v| v);

    let status = if all_healthy {
        "healthy"
    } else if critical_healthy {
        "degraded"
    } else {
        "unhealthy"
    };

    // Build capabilities
    let capabilities = build_capabilities(&components);

    // Determine degradation level
    let degradation_level = if all_healthy {
        None
    } else if critical_healthy {
        Some(determine_degradation_mode(&components))
    } else {
        Some("minimal".into())
    };

    debug!(
        status = status,
        healthy_components = components.values().filter(|&&v| v).count(),
        total_components = components.len(),
        "Health check completed"
    );

    Json(HealthResponse {
        status: status.into(),
        version: VERSION.into(),
        components,
        component_details,
        degradation_level,
        capabilities,
        timestamp: Utc::now(),
    })
}

/// Handle the GET /health/live endpoint.
///
/// Kubernetes liveness probe. Returns 200 if the service process is running.
/// This is a simple check that doesn't verify external dependencies.
pub async fn liveness() -> Json<LivenessResponse> {
    Json(LivenessResponse::default())
}

/// Handle the GET /health/ready endpoint.
///
/// Kubernetes readiness probe. Returns 200 if the service is ready to accept requests.
/// Checks that the embedding service is reachable and at least one search backend is available.
///
/// # Errors
///
/// Returns 503 Service Unavailable if the embedding service is down or all search backends are
/// down.
pub async fn readiness(State(state): State<Arc<AppState>>) -> ApiResult<Json<ReadinessResponse>> {
    // Check embedding and search backends in parallel
    let (embedding_healthy, (qdrant_healthy, opensearch_healthy)) =
        tokio::join!(state.embedding.health_check(), quick_health_check(&state),);

    let search_ready = qdrant_healthy || opensearch_healthy;

    if !embedding_healthy {
        warn!("Readiness check failed: embedding service unavailable");
        return Err(ApiError::service_unavailable(
            "Service not ready: embedding service unavailable",
        ));
    }

    if !search_ready {
        warn!("Readiness check failed: all search backends unavailable");
        return Err(ApiError::service_unavailable(
            "Service not ready: all search backends unavailable",
        ));
    }

    let degradation_mode = if qdrant_healthy && opensearch_healthy {
        None
    } else if qdrant_healthy {
        Some("semantic_only".into())
    } else {
        Some("keyword_only".into())
    };

    Ok(Json(ReadinessResponse {
        status: "ready".into(),
        degradation_mode,
    }))
}

/// Check the embedding service health.
async fn check_embedding(state: &AppState) -> ComponentHealth {
    let start = Instant::now();

    let healthy = state.embedding.health_check().await;

    if !healthy {
        warn!("Embedding service health check failed");
    }

    ComponentHealth {
        name: "embedding".into(),
        healthy,
        latency_ms: Some(start.elapsed().as_secs_f64() * 1000.0),
        error: if healthy {
            None
        } else {
            Some("Embedding service unreachable or returned error".into())
        },
        circuit_state: None,
    }
}

/// Check the search backend health (Qdrant and `OpenSearch`).
async fn check_search_backends(state: &AppState) -> (ComponentHealth, ComponentHealth) {
    let start = Instant::now();

    // Check Qdrant
    let qdrant_healthy = match state.hybrid.health_check_semantic().await {
        Ok(()) => true,
        Err(e) => {
            warn!(error = %e, "Qdrant health check failed");
            false
        }
    };
    let qdrant_latency = start.elapsed().as_secs_f64() * 1000.0;

    let qdrant = ComponentHealth {
        name: "qdrant".into(),
        healthy: qdrant_healthy,
        latency_ms: Some(qdrant_latency),
        error: if qdrant_healthy {
            None
        } else {
            Some("Health check failed".into())
        },
        circuit_state: None,
    };

    // Check OpenSearch
    let opensearch_start = Instant::now();
    let opensearch_healthy = match state.hybrid.health_check_keyword().await {
        Ok(()) => true,
        Err(e) => {
            warn!(error = %e, "OpenSearch health check failed");
            false
        }
    };
    let opensearch_latency = opensearch_start.elapsed().as_secs_f64() * 1000.0;

    let opensearch = ComponentHealth {
        name: "opensearch".into(),
        healthy: opensearch_healthy,
        latency_ms: Some(opensearch_latency),
        error: if opensearch_healthy {
            None
        } else {
            Some("Health check failed".into())
        },
        circuit_state: None,
    };

    (qdrant, opensearch)
}

/// Check the reranker health.
async fn check_reranker(state: &AppState) -> ComponentHealth {
    let start = Instant::now();

    let healthy = if let Some(ref reranker) = state.reranker {
        match reranker.health_check().await {
            Ok(is_healthy) => is_healthy,
            Err(e) => {
                warn!(error = %e, "Reranker health check failed");
                false
            }
        }
    } else {
        false
    };

    ComponentHealth {
        name: "reranker".into(),
        healthy,
        latency_ms: Some(start.elapsed().as_secs_f64() * 1000.0),
        error: if healthy {
            None
        } else {
            Some("Health check failed or reranker not configured".into())
        },
        circuit_state: None,
    }
}

/// Quick health check for readiness probe (minimal overhead).
async fn quick_health_check(state: &AppState) -> (bool, bool) {
    // Run both checks in parallel
    let (qdrant, opensearch) = tokio::join!(
        state.hybrid.health_check_semantic(),
        state.hybrid.health_check_keyword()
    );

    (qdrant.is_ok(), opensearch.is_ok())
}

/// Build capabilities map based on component health.
fn build_capabilities(components: &HashMap<String, bool>) -> HashMap<String, bool> {
    let qdrant_healthy = components.get("qdrant").copied().unwrap_or(false);
    let opensearch_healthy = components.get("opensearch").copied().unwrap_or(false);
    let reranker_healthy = components.get("reranker").copied().unwrap_or(false);

    let mut capabilities = HashMap::new();
    capabilities.insert("semantic_search".into(), qdrant_healthy);
    capabilities.insert("keyword_search".into(), opensearch_healthy);
    capabilities.insert("hybrid_search".into(), qdrant_healthy && opensearch_healthy);
    capabilities.insert("reranking".into(), reranker_healthy);
    capabilities
}

/// Determine the degradation mode based on component health.
fn determine_degradation_mode(components: &HashMap<String, bool>) -> String {
    let qdrant_healthy = components.get("qdrant").copied().unwrap_or(false);
    let opensearch_healthy = components.get("opensearch").copied().unwrap_or(false);

    match (qdrant_healthy, opensearch_healthy) {
        (true, true) => "hybrid_full".into(),
        (true, false) => "semantic_only".into(),
        (false, true) => "keyword_only".into(),
        (false, false) => "minimal".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_capabilities_all_healthy() {
        let mut components = HashMap::new();
        components.insert("qdrant".into(), true);
        components.insert("opensearch".into(), true);
        components.insert("reranker".into(), true);

        let capabilities = build_capabilities(&components);

        assert!(capabilities["semantic_search"]);
        assert!(capabilities["keyword_search"]);
        assert!(capabilities["hybrid_search"]);
        assert!(capabilities["reranking"]);
    }

    #[test]
    fn test_build_capabilities_qdrant_only() {
        let mut components = HashMap::new();
        components.insert("qdrant".into(), true);
        components.insert("opensearch".into(), false);
        components.insert("reranker".into(), false);

        let capabilities = build_capabilities(&components);

        assert!(capabilities["semantic_search"]);
        assert!(!capabilities["keyword_search"]);
        assert!(!capabilities["hybrid_search"]);
        assert!(!capabilities["reranking"]);
    }

    #[test]
    fn test_build_capabilities_opensearch_only() {
        let mut components = HashMap::new();
        components.insert("qdrant".into(), false);
        components.insert("opensearch".into(), true);
        components.insert("reranker".into(), true);

        let capabilities = build_capabilities(&components);

        assert!(!capabilities["semantic_search"]);
        assert!(capabilities["keyword_search"]);
        assert!(!capabilities["hybrid_search"]);
        assert!(capabilities["reranking"]);
    }

    #[test]
    fn test_determine_degradation_mode() {
        let mut components = HashMap::new();

        // Both healthy
        components.insert("qdrant".into(), true);
        components.insert("opensearch".into(), true);
        assert_eq!(determine_degradation_mode(&components), "hybrid_full");

        // Only qdrant
        components.insert("opensearch".into(), false);
        assert_eq!(determine_degradation_mode(&components), "semantic_only");

        // Only opensearch
        components.insert("qdrant".into(), false);
        components.insert("opensearch".into(), true);
        assert_eq!(determine_degradation_mode(&components), "keyword_only");

        // Neither
        components.insert("opensearch".into(), false);
        assert_eq!(determine_degradation_mode(&components), "minimal");
    }

    #[test]
    fn test_liveness_response() {
        let response = LivenessResponse::default();
        assert_eq!(response.status, "alive");
    }

    #[test]
    fn test_readiness_response_default() {
        let response = ReadinessResponse::default();
        assert_eq!(response.status, "ready");
        assert!(response.degradation_mode.is_none());
    }
}
