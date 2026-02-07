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
    /// Capability flags: which features are configured and available.
    capabilities: Capabilities,
}

/// Individual services health status.
///
/// Status values:
/// - `"healthy"`: Model is loaded and ready to serve requests.
/// - `"disabled"`: Feature is turned off by configuration.
/// - `"unavailable"`: Feature is enabled in config but failed to load.
/// - `"unhealthy"`: Service is enabled and loaded but not responding.
#[derive(Debug, Serialize)]
pub struct ServicesHealth {
    /// Embedding service status.
    embedding: &'static str,
    /// Reranker service status.
    reranker: &'static str,
    /// vLLM service status.
    vllm: &'static str,
}

/// Capability flags showing which features are configured and available.
#[derive(Debug, Serialize)]
pub struct Capabilities {
    /// Whether embeddings are available.
    embeddings: CapabilityStatus,
    /// Whether reranking is available.
    reranker: CapabilityStatus,
    /// Whether chat completions (vLLM proxy) are available.
    chat_completions: CapabilityStatus,
}

/// Status of a single capability.
#[derive(Debug, Serialize)]
pub struct CapabilityStatus {
    /// Whether the feature is enabled in configuration.
    enabled: bool,
    /// Whether the feature is actually ready to serve requests.
    available: bool,
    /// Model identifier (if applicable).
    #[serde(skip_serializing_if = "Option::is_none")]
    model: Option<String>,
}

/// Health check endpoint.
///
/// Returns overall health, status of individual services, and capability flags.
/// The capability flags make it deterministic whether a feature is:
/// - Disabled by configuration (`enabled=false, available=false`)
/// - Enabled but failed to load (`enabled=true, available=false`)
/// - Enabled and ready (`enabled=true, available=true`)
pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let embedding_available = state.embedding_model.is_some();
    let embedding_status = if embedding_available {
        "healthy"
    } else if state.config.embedding.enabled {
        "unavailable"
    } else {
        "disabled"
    };

    let reranker_available = state.reranker_model.is_some();
    let reranker_status = if reranker_available {
        "healthy"
    } else if state.config.reranker.enabled {
        "unavailable"
    } else {
        "disabled"
    };

    let (vllm_available, vllm_status) = match &state.vllm_client {
        Some(client) => {
            if client.health_check().await {
                (true, "healthy")
            } else {
                (false, "unhealthy")
            }
        }
        None => (false, "disabled"),
    };

    // Overall status is "degraded" if any enabled service is unavailable/unhealthy
    let overall = if (state.config.embedding.enabled && !embedding_available)
        || (state.config.reranker.enabled && !reranker_available)
        || (state.config.vllm.enabled && !vllm_available)
    {
        "degraded"
    } else {
        "healthy"
    };

    Json(HealthResponse {
        status: overall,
        services: ServicesHealth {
            embedding: embedding_status,
            reranker: reranker_status,
            vllm: vllm_status,
        },
        capabilities: Capabilities {
            embeddings: CapabilityStatus {
                enabled: state.config.embedding.enabled,
                available: embedding_available,
                model: state
                    .embedding_model
                    .as_ref()
                    .map(|m| m.model_id().to_string()),
            },
            reranker: CapabilityStatus {
                enabled: state.config.reranker.enabled,
                available: reranker_available,
                model: state
                    .reranker_model
                    .as_ref()
                    .map(|m| m.model_id().to_string()),
            },
            chat_completions: CapabilityStatus {
                enabled: state.config.vllm.enabled,
                available: vllm_available,
                model: if vllm_available {
                    Some(state.config.vllm.default_model.clone())
                } else {
                    None
                },
            },
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

/// Readiness probe response.
#[derive(Debug, Serialize)]
pub struct ReadinessResponse {
    /// Status: `"ready"` or `"not_ready"`.
    status: &'static str,
    /// Reason for not being ready (if applicable).
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
}

/// Readiness probe endpoint.
///
/// Returns "ready" if at least one capability (embedding, reranker, or chat)
/// is enabled AND available. Returns `"not_ready"` if all enabled capabilities
/// have failed to load.
pub async fn readiness(State(state): State<Arc<AppState>>) -> Json<ReadinessResponse> {
    let embedding_ok = !state.config.embedding.enabled || state.embedding_model.is_some();
    let reranker_ok = !state.config.reranker.enabled || state.reranker_model.is_some();
    let vllm_ok = !state.config.vllm.enabled || state.vllm_client.is_some();

    // At least one service must be enabled
    let any_enabled =
        state.config.embedding.enabled || state.config.reranker.enabled || state.config.vllm.enabled;

    if !any_enabled {
        return Json(ReadinessResponse {
            status: "not_ready",
            reason: Some("No capabilities are enabled".into()),
        });
    }

    // Ready if all enabled capabilities are available
    if embedding_ok && reranker_ok && vllm_ok {
        Json(ReadinessResponse {
            status: "ready",
            reason: None,
        })
    } else {
        let mut failures = Vec::new();
        if !embedding_ok {
            failures.push("embedding");
        }
        if !reranker_ok {
            failures.push("reranker");
        }
        if !vllm_ok {
            failures.push("vllm");
        }
        Json(ReadinessResponse {
            status: "not_ready",
            reason: Some(format!(
                "Enabled but unavailable: {}",
                failures.join(", ")
            )),
        })
    }
}

/// Prometheus metrics endpoint.
///
/// Returns metrics in Prometheus text format.
pub async fn metrics() -> String {
    metrics::gather_metrics()
}
