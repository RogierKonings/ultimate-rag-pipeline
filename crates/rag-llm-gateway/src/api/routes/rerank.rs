//! Reranking endpoints.

use std::sync::Arc;

use axum::{extract::State, Json};
use tracing::{info, instrument};

use crate::api::AppState;
use crate::error::{GatewayError, Result};
use crate::metrics;
use crate::reranker::{RerankRequest, RerankResponse};

/// Create rerank endpoint.
///
/// Reranks documents based on relevance to a query using a cross-encoder model.
/// Returns documents sorted by relevance score in descending order.
///
/// Returns 503 Service Unavailable if the reranker model is not loaded
/// (either disabled by configuration or failed to load at startup).
#[instrument(skip(state, request), fields(num_docs = request.documents.len()))]
pub async fn create_rerank(
    State(state): State<Arc<AppState>>,
    Json(request): Json<RerankRequest>,
) -> Result<Json<RerankResponse>> {
    let model = state.reranker_model.as_ref().ok_or_else(|| {
        if state.config.reranker.enabled {
            GatewayError::ServiceUnavailable(
                "Reranker model failed to load at startup. Check service logs for details.".into(),
            )
        } else {
            GatewayError::ServiceUnavailable(
                "Reranker is disabled by configuration (RERANKER_ENABLED=false).".into(),
            )
        }
    })?;

    if request.documents.is_empty() {
        return Err(GatewayError::BadRequest(
            "Documents list cannot be empty".into(),
        ));
    }

    // Clone Arc for the blocking task
    let model = model.clone();

    // Run reranking on a blocking task to avoid blocking the async runtime.
    // The RerankerModel uses a Mutex internally for the fastembed TextRerank.
    let response = tokio::task::spawn_blocking(move || model.rerank(&request))
        .await
        .map_err(|e| GatewayError::Internal(format!("Rerank task failed: {e}")))?
        .inspect_err(|_| {
            metrics::record_request("reranker", "/v1/rerank", "error", 0.0);
        })?;

    info!(
        num_results = response.results.len(),
        elapsed_ms = response.processing_time_ms,
        "Reranking completed"
    );

    metrics::record_request(
        "reranker",
        "/v1/rerank",
        "success",
        response.processing_time_ms / 1000.0,
    );

    Ok(Json(response))
}
