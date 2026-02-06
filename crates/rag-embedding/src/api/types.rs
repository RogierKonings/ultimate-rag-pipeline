//! Request and response types for the embedding API.
//!
//! These types are OpenAI-compatible for drop-in replacement.

use serde::{Deserialize, Serialize};

/// Input can be a single string or array of strings.
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum StringOrArray {
    /// Single string input.
    Single(String),
    /// Array of string inputs.
    Array(Vec<String>),
}

impl StringOrArray {
    /// Convert to a vector of strings.
    #[must_use]
    pub fn into_vec(self) -> Vec<String> {
        match self {
            Self::Single(s) => vec![s],
            Self::Array(v) => v,
        }
    }

    /// Check if empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        match self {
            Self::Single(s) => s.is_empty(),
            Self::Array(v) => v.is_empty() || v.iter().all(String::is_empty),
        }
    }

    /// Get the number of items.
    #[must_use]
    pub fn len(&self) -> usize {
        match self {
            Self::Single(_) => 1,
            Self::Array(v) => v.len(),
        }
    }
}

/// OpenAI-compatible embedding request.
#[derive(Debug, Clone, Deserialize)]
pub struct EmbeddingRequest {
    /// Input text(s) to embed.
    pub input: StringOrArray,
    /// Model to use (ignored, uses configured model).
    #[serde(default)]
    pub model: Option<String>,
    /// Encoding format (only "float" supported).
    #[serde(default = "default_encoding_format")]
    pub encoding_format: String,
}

fn default_encoding_format() -> String {
    "float".into()
}

/// Single embedding result.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingData {
    /// The embedding vector.
    pub embedding: Vec<f32>,
    /// Index of the input text.
    pub index: usize,
    /// Object type (always "embedding").
    pub object: &'static str,
}

impl EmbeddingData {
    /// Create a new embedding data object.
    #[must_use]
    pub const fn new(embedding: Vec<f32>, index: usize) -> Self {
        Self {
            embedding,
            index,
            object: "embedding",
        }
    }
}

/// Token usage information.
#[derive(Debug, Clone, Serialize)]
pub struct Usage {
    /// Number of tokens in the input prompts.
    pub prompt_tokens: usize,
    /// Total tokens used.
    pub total_tokens: usize,
}

impl Usage {
    /// Estimate token count from texts.
    ///
    /// Uses rough approximation: ~0.75 tokens per word.
    #[must_use]
    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )]
    pub fn estimate(texts: &[String]) -> Self {
        let total: usize = texts
            .iter()
            .map(|t| (t.split_whitespace().count() as f64 * 0.75).ceil() as usize)
            .sum();

        Self {
            prompt_tokens: total,
            total_tokens: total,
        }
    }
}

/// OpenAI-compatible embedding response.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingResponse {
    /// Embedding data for each input.
    pub data: Vec<EmbeddingData>,
    /// Model used for generation.
    pub model: String,
    /// Object type (always "list").
    pub object: &'static str,
    /// Token usage.
    pub usage: Usage,
}

impl EmbeddingResponse {
    /// Create a new embedding response.
    #[must_use]
    pub fn new(embeddings: Vec<Vec<f32>>, model: String, texts: &[String]) -> Self {
        let data = embeddings
            .into_iter()
            .enumerate()
            .map(|(i, emb)| EmbeddingData::new(emb, i))
            .collect();

        Self {
            data,
            model,
            object: "list",
            usage: Usage::estimate(texts),
        }
    }
}

// Health types re-exported from rag-types.
pub use rag_types::{HealthResponse, LivenessResponse, ReadinessResponse};

/// Model information for /v1/models endpoint.
#[derive(Debug, Clone, Serialize)]
pub struct ModelInfo {
    /// Model identifier.
    pub id: String,
    /// Object type.
    pub object: &'static str,
    /// Creation timestamp.
    pub created: i64,
    /// Owner.
    pub owned_by: &'static str,
    /// Permissions (empty).
    pub permission: Vec<()>,
    /// Root model.
    pub root: String,
    /// Parent model.
    pub parent: Option<String>,
    /// Model metadata.
    pub metadata: ModelMetadata,
}

/// Model metadata.
#[derive(Debug, Clone, Serialize)]
pub struct ModelMetadata {
    /// Embedding dimensions.
    pub dimension: usize,
    /// Maximum batch size.
    pub max_batch_size: usize,
}

/// List models response.
#[derive(Debug, Clone, Serialize)]
pub struct ModelsResponse {
    /// Object type.
    pub object: &'static str,
    /// Available models.
    pub data: Vec<ModelInfo>,
}

/// Service info response for root endpoint.
#[derive(Debug, Clone, Serialize)]
pub struct ServiceInfo {
    /// Service name.
    pub service: &'static str,
    /// Service version.
    pub version: &'static str,
    /// Loaded model.
    pub model: String,
    /// Available endpoints.
    pub endpoints: ServiceEndpoints,
}

/// Available endpoints.
#[derive(Debug, Clone, Serialize)]
pub struct ServiceEndpoints {
    /// Embeddings endpoint.
    pub embeddings: &'static str,
    /// Models endpoint.
    pub models: &'static str,
    /// Health endpoint.
    pub health: &'static str,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_string_or_array_single() {
        let input = StringOrArray::Single("hello".into());
        assert_eq!(input.len(), 1);
        assert!(!input.is_empty());
        assert_eq!(input.into_vec(), vec!["hello"]);
    }

    #[test]
    fn test_string_or_array_array() {
        let input = StringOrArray::Array(vec!["hello".into(), "world".into()]);
        assert_eq!(input.len(), 2);
        assert!(!input.is_empty());
        assert_eq!(input.into_vec(), vec!["hello", "world"]);
    }

    #[test]
    fn test_usage_estimate() {
        let texts = vec!["hello world".into(), "foo bar baz".into()];
        let usage = Usage::estimate(&texts);
        // 2 words + 3 words = 5 words * 0.75 ≈ 4 tokens
        assert!(usage.total_tokens >= 3);
        assert!(usage.total_tokens <= 5);
    }

    #[test]
    fn test_embedding_response_creation() {
        let embeddings = vec![vec![0.1, 0.2], vec![0.3, 0.4]];
        let texts = vec!["hello".into(), "world".into()];
        let response = EmbeddingResponse::new(embeddings, "test-model".into(), &texts);

        assert_eq!(response.data.len(), 2);
        assert_eq!(response.data[0].index, 0);
        assert_eq!(response.data[1].index, 1);
        assert_eq!(response.object, "list");
        assert_eq!(response.model, "test-model");
    }

    #[test]
    fn test_deserialize_embedding_request_single() {
        let json = r#"{"input": "hello world"}"#;
        let request: EmbeddingRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.input.len(), 1);
    }

    #[test]
    fn test_deserialize_embedding_request_array() {
        let json = r#"{"input": ["hello", "world"], "model": "test"}"#;
        let request: EmbeddingRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.input.len(), 2);
        assert_eq!(request.model, Some("test".into()));
    }
}
