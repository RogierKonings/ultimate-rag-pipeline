//! API response types for the retrieval service.
//!
//! This module provides response types, metrics, and debug information
//! for the HTTP API.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::SearchMode;

// Health types re-exported from rag-types for a canonical format across services.
pub use rag_types::{
    ComponentHealth, HealthResponse, LivenessResponse, ReadinessResponse,
};

fn default_one() -> u32 {
    1
}

fn default_semantic_weight() -> f32 {
    0.7
}

fn default_keyword_weight() -> f32 {
    0.3
}

fn default_fusion_method() -> String {
    "rrf".to_string()
}

fn default_rrf_k() -> i32 {
    60
}

/// A single retrieved document/chunk in the response.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct RetrievedDocument {
    /// Unique chunk identifier.
    pub chunk_id: Uuid,

    /// Parent document identifier.
    pub document_id: Uuid,

    /// The actual content of the chunk.
    pub content: String,

    /// Combined/final score after all processing.
    pub score: f32,

    /// Document title.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,

    /// Source URI of the document.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,

    /// Source type (e.g., "documentation", "kb_article").
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_type: Option<String>,

    /// Index of this chunk within the document.
    #[serde(default)]
    pub chunk_index: u32,

    /// Total number of chunks in the document.
    #[serde(default = "default_one")]
    pub total_chunks: u32,

    /// When the document was created.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_at: Option<DateTime<Utc>>,

    /// When the document was last updated.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<DateTime<Utc>>,

    /// Score from semantic (vector) search.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_score: Option<f32>,

    /// Score from keyword (BM25) search.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyword_score: Option<f32>,

    /// Score from cross-encoder reranking.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rerank_score: Option<f32>,

    /// Additional metadata from the document.
    #[serde(default)]
    pub metadata: serde_json::Value,

    /// Highlighted text fragments from keyword search.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub highlights: Option<Vec<String>>,
}

impl RetrievedDocument {
    /// Create a new retrieved document with required fields.
    #[must_use]
    pub fn new(chunk_id: Uuid, document_id: Uuid, content: String, score: f32) -> Self {
        Self {
            chunk_id,
            document_id,
            content,
            score,
            title: None,
            source: None,
            source_type: None,
            chunk_index: 0,
            total_chunks: 1,
            created_at: None,
            updated_at: None,
            semantic_score: None,
            keyword_score: None,
            rerank_score: None,
            metadata: serde_json::Value::Object(serde_json::Map::new()),
            highlights: None,
        }
    }
}

/// Metrics for the search operation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct SearchMetrics {
    /// Time spent preprocessing the query (ms).
    #[serde(default)]
    pub query_preprocessing_ms: f64,

    /// Time spent generating query embedding (ms).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub embedding_ms: Option<f64>,

    /// Time spent on semantic (vector) search (ms).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_search_ms: Option<f64>,

    /// Time spent on keyword (BM25) search (ms).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyword_search_ms: Option<f64>,

    /// Time spent on RRF fusion (ms).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fusion_ms: Option<f64>,

    /// Time spent on reranking (ms).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rerank_ms: Option<f64>,

    /// Total request time (ms).
    pub total_ms: f64,

    /// Number of results from semantic search.
    #[serde(default)]
    pub semantic_results_count: usize,

    /// Number of results from keyword search.
    #[serde(default)]
    pub keyword_results_count: usize,

    /// Number of results after fusion.
    #[serde(default)]
    pub fused_results_count: usize,

    /// Final number of results returned.
    #[serde(default)]
    pub final_results_count: usize,
}

/// Debug information for the retrieval pipeline.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct DebugInfo {
    /// Number of candidates from semantic search.
    #[serde(default)]
    pub semantic_candidates: usize,

    /// Number of candidates from keyword search.
    #[serde(default)]
    pub keyword_candidates: usize,

    /// Number of results after fusion.
    #[serde(default)]
    pub after_fusion: usize,

    /// Number of results after reranking.
    #[serde(default)]
    pub after_rerank: usize,

    /// Number of results after ACL filtering.
    #[serde(default)]
    pub after_acl: usize,

    /// Time spent preprocessing (ms).
    #[serde(default)]
    pub preprocessing_latency_ms: f64,

    /// Time spent embedding (ms).
    #[serde(default)]
    pub embedding_latency_ms: f64,

    /// Time spent on semantic search (ms).
    #[serde(default)]
    pub semantic_search_latency_ms: f64,

    /// Time spent on keyword search (ms).
    #[serde(default)]
    pub keyword_search_latency_ms: f64,

    /// Time spent on fusion (ms).
    #[serde(default)]
    pub fusion_latency_ms: f64,

    /// Time spent on reranking (ms).
    #[serde(default)]
    pub rerank_latency_ms: f64,

    /// Time spent on ACL filtering (ms).
    #[serde(default)]
    pub acl_filter_latency_ms: f64,

    /// Total latency (ms).
    #[serde(default)]
    pub total_latency_ms: f64,

    /// Embedding model used.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub embedding_model: Option<String>,

    /// Reranker model used.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rerank_model: Option<String>,

    /// Fusion method used.
    #[serde(default = "default_fusion_method")]
    pub fusion_method: String,

    /// Semantic weight used.
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,

    /// Keyword weight used.
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,

    /// RRF k parameter.
    #[serde(default = "default_rrf_k")]
    pub rrf_k: i32,
}

/// Response from the retrieve endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct RetrieveResponse {
    /// The search results.
    pub results: Vec<RetrievedDocument>,

    /// Total number of results returned.
    pub total_results: usize,

    /// The original query.
    pub query: String,

    /// The search mode used.
    pub mode: SearchMode,

    /// Search operation metrics.
    pub metrics: SearchMetrics,

    /// Unique identifier for this query.
    pub query_id: Uuid,

    /// When this query was processed.
    pub processed_at: DateTime<Utc>,

    /// Debug information (optional).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub debug: Option<DebugInfo>,

    /// Current degradation mode if service is degraded.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub degradation_mode: Option<String>,

    /// Components that were used for this search.
    #[serde(default)]
    pub components_used: Vec<String>,

    /// Components that were skipped due to failures.
    #[serde(default)]
    pub components_skipped: Vec<String>,
}

impl RetrieveResponse {
    /// Create a new retrieve response.
    #[must_use]
    pub fn new(
        results: Vec<RetrievedDocument>,
        query: String,
        mode: SearchMode,
        metrics: SearchMetrics,
    ) -> Self {
        Self {
            total_results: results.len(),
            results,
            query,
            mode,
            metrics,
            query_id: Uuid::new_v4(),
            processed_at: Utc::now(),
            debug: None,
            degradation_mode: None,
            components_used: Vec::new(),
            components_skipped: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_health_response_serialization() {
        let response = HealthResponse::healthy("1.0.0");
        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"status\":\"healthy\""));
        assert!(json.contains("\"version\":\"1.0.0\""));

        let deserialized: HealthResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.status, "healthy");
        assert_eq!(deserialized.version, "1.0.0");
    }

    #[test]
    fn test_retrieve_response_creation() {
        let results = vec![RetrievedDocument::new(
            Uuid::new_v4(),
            Uuid::new_v4(),
            "test content".into(),
            0.95,
        )];
        let metrics = SearchMetrics::default();

        let response = RetrieveResponse::new(
            results,
            "test query".into(),
            SearchMode::Hybrid,
            metrics,
        );

        assert_eq!(response.total_results, 1);
        assert_eq!(response.query, "test query");
        assert_eq!(response.mode, SearchMode::Hybrid);
    }

    #[test]
    fn test_retrieved_document_creation() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let doc = RetrievedDocument::new(chunk_id, document_id, "content".into(), 0.9);

        assert_eq!(doc.chunk_id, chunk_id);
        assert_eq!(doc.document_id, document_id);
        assert_eq!(doc.content, "content");
        assert!((doc.score - 0.9).abs() < f32::EPSILON);
    }

    #[test]
    fn test_liveness_response_default() {
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
