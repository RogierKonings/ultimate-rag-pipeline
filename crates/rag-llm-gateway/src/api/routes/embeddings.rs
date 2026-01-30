//! Embedding endpoints.

use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use tracing::{info, instrument};

use crate::api::AppState;
use crate::error::{GatewayError, Result};
use crate::metrics;

/// Embedding request (OpenAI-compatible).
#[derive(Debug, Deserialize)]
pub struct EmbeddingRequest {
    /// Input text(s) to embed.
    pub input: EmbeddingInput,
    /// Model to use (optional, uses configured default).
    /// Currently not used - always uses the configured model.
    #[serde(default)]
    #[allow(dead_code)]
    pub model: Option<String>,
}

/// Embedding input - either a single string or multiple strings.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum EmbeddingInput {
    /// Single text input.
    Single(String),
    /// Multiple text inputs.
    Multiple(Vec<String>),
}

impl EmbeddingInput {
    /// Convert to a vector of strings.
    #[must_use]
    pub fn into_vec(self) -> Vec<String> {
        match self {
            Self::Single(s) => vec![s],
            Self::Multiple(v) => v,
        }
    }

    /// Get the number of inputs.
    #[must_use]
    pub fn len(&self) -> usize {
        match self {
            Self::Single(_) => 1,
            Self::Multiple(v) => v.len(),
        }
    }

    /// Check if empty.
    #[must_use]
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// Embedding response (OpenAI-compatible).
#[derive(Debug, Serialize)]
pub struct EmbeddingResponse {
    /// Object type (always "list").
    pub object: &'static str,
    /// Embedding data.
    pub data: Vec<EmbeddingData>,
    /// Model used.
    pub model: String,
    /// Token usage.
    pub usage: EmbeddingUsage,
}

/// Individual embedding data.
#[derive(Debug, Serialize)]
pub struct EmbeddingData {
    /// Object type (always "embedding").
    pub object: &'static str,
    /// The embedding vector.
    pub embedding: Vec<f32>,
    /// Index in the input array.
    pub index: usize,
}

/// Token usage for embeddings.
#[derive(Debug, Serialize)]
pub struct EmbeddingUsage {
    /// Number of prompt tokens.
    pub prompt_tokens: usize,
    /// Total tokens used.
    pub total_tokens: usize,
}

/// Create embeddings endpoint.
///
/// Generates embeddings for the provided input text(s).
/// Compatible with OpenAI's `/v1/embeddings` API.
#[instrument(skip(state, request), fields(num_inputs = request.input.len()))]
pub async fn create_embeddings(
    State(state): State<Arc<AppState>>,
    Json(request): Json<EmbeddingRequest>,
) -> Result<Json<EmbeddingResponse>> {
    let model = state
        .embedding_model
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("Embedding service not available".into()))?;

    let texts = request.input.into_vec();
    let num_texts = texts.len();

    if num_texts == 0 {
        return Err(GatewayError::BadRequest("Input cannot be empty".into()));
    }

    let start = Instant::now();

    // Clone for the blocking task
    let model_clone = model.clone();
    let texts_clone = texts.clone();

    // Run embedding on blocking task to avoid blocking the async runtime
    let embeddings = tokio::task::spawn_blocking(move || model_clone.embed(&texts_clone))
        .await
        .map_err(|e| GatewayError::Internal(format!("Task failed: {e}")))?
        .map_err(GatewayError::from)?;

    let elapsed = start.elapsed();

    info!(
        num_embeddings = embeddings.len(),
        elapsed_ms = elapsed.as_millis(),
        "Generated embeddings"
    );

    metrics::record_request("embedding", "/v1/embeddings", "success", elapsed.as_secs_f64());
    #[allow(clippy::cast_precision_loss)]
    metrics::EMBEDDINGS_GENERATED.inc_by(num_texts as f64);

    // Estimate tokens (rough approximation: ~1.3 tokens per word)
    let total_tokens: usize = texts.iter().map(|t| t.split_whitespace().count()).sum();

    let data: Vec<EmbeddingData> = embeddings
        .into_iter()
        .enumerate()
        .map(|(i, emb)| EmbeddingData {
            object: "embedding",
            embedding: emb,
            index: i,
        })
        .collect();

    let response = EmbeddingResponse {
        object: "list",
        data,
        model: model.model_id().to_string(),
        usage: EmbeddingUsage {
            prompt_tokens: total_tokens,
            total_tokens,
        },
    };

    Ok(Json(response))
}
