//! Reranking endpoints.

use std::sync::Arc;

use axum::{extract::State, Json};
use tracing::instrument;

use crate::api::AppState;
use crate::error::{GatewayError, Result};
use crate::reranker::{RerankRequest, RerankResponse};

/// Create rerank endpoint.
///
/// Reranks documents based on relevance to a query using a cross-encoder model.
/// Returns documents sorted by relevance score in descending order.
#[instrument(skip(state, request), fields(num_docs = request.documents.len()))]
pub async fn create_rerank(
    State(state): State<Arc<AppState>>,
    Json(request): Json<RerankRequest>,
) -> Result<Json<RerankResponse>> {
    let model = state
        .reranker_model
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("Reranker service not available".into()))?;

    let response = model.rerank(request).await?;

    Ok(Json(response))
}
