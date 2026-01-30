//! Models listing endpoint.

use std::sync::Arc;

use axum::{extract::State, Json};
use serde::Serialize;

use crate::api::AppState;

/// Model information.
#[derive(Debug, Serialize)]
pub struct ModelInfo {
    /// Model identifier.
    id: String,
    /// Object type (always "model").
    object: &'static str,
    /// Owner/source of the model.
    owned_by: String,
}

/// Models list response (OpenAI-compatible).
#[derive(Debug, Serialize)]
pub struct ModelsResponse {
    /// Object type (always "list").
    object: &'static str,
    /// Available models.
    data: Vec<ModelInfo>,
}

/// List available models endpoint.
///
/// Returns a list of all available models across services
/// (embedding, reranker, LLM).
/// Compatible with `OpenAI`'s `/v1/models` API.
pub async fn list_models(State(state): State<Arc<AppState>>) -> Json<ModelsResponse> {
    let mut models = Vec::new();

    // Add embedding model if available
    if let Some(embedding) = &state.embedding_model {
        models.push(ModelInfo {
            id: embedding.model_id().to_string(),
            object: "model",
            owned_by: "embedding-service".into(),
        });
    }

    // Add reranker model if available
    if state.reranker_model.is_some() {
        models.push(ModelInfo {
            id: state.config.reranker.model.clone(),
            object: "model",
            owned_by: "reranker-service".into(),
        });
    }

    // Add vLLM model if available
    if state.vllm_client.is_some() {
        models.push(ModelInfo {
            id: state.config.vllm.default_model.clone(),
            object: "model",
            owned_by: "vllm".into(),
        });
    }

    Json(ModelsResponse {
        object: "list",
        data: models,
    })
}
