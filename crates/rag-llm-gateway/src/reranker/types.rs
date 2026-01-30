//! Reranker request/response types.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Rerank request.
#[derive(Debug, Clone, Deserialize)]
pub struct RerankRequest {
    /// Model to use (ignored, uses configured model).
    #[serde(default)]
    pub model: Option<String>,

    /// Query to rank documents against.
    pub query: String,

    /// Documents to rerank.
    pub documents: Vec<String>,

    /// Optional document IDs.
    #[serde(default)]
    pub doc_ids: Option<Vec<String>>,

    /// Return only top K results.
    #[serde(default)]
    pub top_k: Option<usize>,

    /// Minimum score threshold.
    #[serde(default)]
    pub min_score: Option<f32>,

    /// Include document text in response.
    #[serde(default = "default_return_documents")]
    pub return_documents: bool,

    /// Request ID.
    #[serde(default = "Uuid::new_v4")]
    pub request_id: Uuid,
}

/// Default value for `return_documents` field.
const fn default_return_documents() -> bool {
    true
}

/// Scored document in response.
#[derive(Debug, Clone, Serialize)]
pub struct ScoredDocument {
    /// Original index in input.
    pub index: usize,

    /// Relevance score.
    pub score: f32,

    /// Document text (if requested).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub document: Option<String>,

    /// Document ID (if provided).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub doc_id: Option<String>,
}

/// Token usage.
#[derive(Debug, Clone, Serialize)]
pub struct RerankUsage {
    pub prompt_tokens: usize,
    pub total_tokens: usize,
}

/// Rerank response.
#[derive(Debug, Clone, Serialize)]
pub struct RerankResponse {
    /// Model used.
    pub model: String,

    /// Ranked results (sorted by score descending).
    pub results: Vec<ScoredDocument>,

    /// Token usage.
    pub usage: RerankUsage,

    /// Processing time in milliseconds.
    pub processing_time_ms: f64,
}
