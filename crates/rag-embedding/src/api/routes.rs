//! HTTP routes for the embedding service.

use std::sync::Arc;
use std::time::Instant;

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use tracing::{info, instrument};

use super::error::{ApiError, ApiResult};
use super::state::AppState;
use super::types::{
    EmbeddingRequest, EmbeddingResponse, HealthResponse, ModelInfo, ModelMetadata,
    ModelsResponse, ServiceEndpoints, ServiceInfo,
};

/// Create the Axum router with all routes.
pub fn create_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/", get(root))
        .route("/health", get(health))
        .route("/v1/embeddings", post(create_embeddings))
        .route("/v1/models", get(list_models))
        .with_state(state)
}

/// Root endpoint with service info.
async fn root(State(state): State<Arc<AppState>>) -> Json<ServiceInfo> {
    Json(ServiceInfo {
        service: "embedding-service",
        version: env!("CARGO_PKG_VERSION"),
        model: state.model_id().to_string(),
        endpoints: ServiceEndpoints {
            embeddings: "/v1/embeddings",
            models: "/v1/models",
            health: "/health",
        },
    })
}

/// Health check endpoint.
async fn health(State(_state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let resp = HealthResponse::healthy(env!("CARGO_PKG_VERSION"))
        .with_component("model", true)
        .with_capability("embeddings", true);

    Json(resp)
}

/// Create embeddings endpoint (OpenAI-compatible).
#[allow(clippy::cast_precision_loss)]
#[instrument(skip(state, request), fields(num_inputs = request.input.len()))]
async fn create_embeddings(
    State(state): State<Arc<AppState>>,
    Json(request): Json<EmbeddingRequest>,
) -> ApiResult<Json<EmbeddingResponse>> {
    // Validate input
    if request.input.is_empty() {
        return Err(ApiError::bad_request("Input cannot be empty"));
    }

    let texts = request.input.into_vec();

    if texts.len() > state.max_batch_size() {
        return Err(ApiError::bad_request(format!(
            "Batch size {} exceeds maximum {}",
            texts.len(),
            state.max_batch_size()
        )));
    }

    let start = Instant::now();

    // Run embedding in blocking task to avoid blocking the runtime
    let model = state.model.clone();
    let texts_clone = texts.clone();

    let embeddings = tokio::task::spawn_blocking(move || model.embed(&texts_clone))
        .await
        .map_err(|e| ApiError::internal(format!("Task failed: {e}")))?
        .map_err(ApiError::from)?;

    let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
    info!(
        num_embeddings = embeddings.len(),
        elapsed_ms = format!("{:.2}", elapsed_ms),
        per_text_ms = format!("{:.2}", elapsed_ms / texts.len() as f64),
        "Generated embeddings"
    );

    let response = EmbeddingResponse::new(embeddings, state.model_id().to_string(), &texts);

    Ok(Json(response))
}

/// List available models endpoint (OpenAI-compatible).
async fn list_models(State(state): State<Arc<AppState>>) -> Json<ModelsResponse> {
    Json(ModelsResponse {
        object: "list",
        data: vec![ModelInfo {
            id: state.model_id().to_string(),
            object: "model",
            created: 0,
            owned_by: "local",
            permission: vec![],
            root: state.model_id().to_string(),
            parent: None,
            metadata: ModelMetadata {
                dimension: state.dimensions(),
                max_batch_size: state.max_batch_size(),
            },
        }],
    })
}
