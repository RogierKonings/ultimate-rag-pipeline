//! API request and response types for the retrieval service.
//!
//! This module provides Pydantic-equivalent Rust types for the HTTP API,
//! including request validation, response serialization, and OpenAPI annotations.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::SearchMode;

// Default value functions for serde

fn default_top_k() -> usize {
    10
}

fn default_semantic_weight() -> f32 {
    0.7
}

fn default_keyword_weight() -> f32 {
    0.3
}

fn default_rerank_top_k() -> usize {
    20
}

fn default_true() -> bool {
    true
}

fn default_aggregation() -> String {
    "rrf".to_string()
}

/// Request body for the retrieve endpoint.
///
/// Supports hybrid, semantic-only, or keyword-only search
/// with filtering, reranking, and pagination.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct RetrieveRequest {
    /// The search query (1-2000 characters).
    pub query: String,

    /// Search mode: hybrid, semantic, or keyword.
    #[serde(default)]
    pub mode: SearchMode,

    /// Number of results to return (1-100, default: 10).
    #[serde(default = "default_top_k")]
    pub top_k: usize,

    /// Weight for semantic search results (0.0-1.0, default: 0.7).
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,

    /// Weight for keyword search results (0.0-1.0, default: 0.3).
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,

    /// Whether to enable cross-encoder reranking.
    #[serde(default)]
    pub rerank: bool,

    /// Number of candidates to rerank (1-100, default: 20).
    #[serde(default = "default_rerank_top_k")]
    pub rerank_top_k: usize,

    /// Additional metadata filters.
    #[serde(default)]
    pub filters: Option<serde_json::Value>,

    /// Minimum score threshold (0.0-1.0, default: 0.0).
    #[serde(default)]
    pub min_score: f32,

    /// Whether to include document metadata in results.
    #[serde(default = "default_true")]
    pub include_metadata: bool,

    /// Whether to include keyword search highlights in results.
    #[serde(default = "default_true")]
    pub include_highlights: bool,
}

impl Default for RetrieveRequest {
    fn default() -> Self {
        Self {
            query: String::new(),
            mode: SearchMode::default(),
            top_k: default_top_k(),
            semantic_weight: default_semantic_weight(),
            keyword_weight: default_keyword_weight(),
            rerank: false,
            rerank_top_k: default_rerank_top_k(),
            filters: None,
            min_score: 0.0,
            include_metadata: true,
            include_highlights: true,
        }
    }
}

impl RetrieveRequest {
    /// Create a new retrieve request with the given query.
    #[must_use]
    pub fn new(query: impl Into<String>) -> Self {
        Self {
            query: query.into(),
            ..Default::default()
        }
    }

    /// Validate the request parameters.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - Query is empty or exceeds 2000 characters
    /// - top_k is 0 or exceeds 100
    /// - semantic_weight or keyword_weight is out of range
    /// - min_score is out of range
    pub fn validate(&self) -> Result<(), ValidationError> {
        if self.query.is_empty() {
            return Err(ValidationError::new("query", "Query cannot be empty"));
        }

        if self.query.len() > 2000 {
            return Err(ValidationError::new(
                "query",
                "Query cannot exceed 2000 characters",
            ));
        }

        if self.top_k == 0 || self.top_k > 100 {
            return Err(ValidationError::new(
                "top_k",
                "top_k must be between 1 and 100",
            ));
        }

        if !(0.0..=1.0).contains(&self.semantic_weight) {
            return Err(ValidationError::new(
                "semantic_weight",
                "semantic_weight must be between 0.0 and 1.0",
            ));
        }

        if !(0.0..=1.0).contains(&self.keyword_weight) {
            return Err(ValidationError::new(
                "keyword_weight",
                "keyword_weight must be between 0.0 and 1.0",
            ));
        }

        if self.rerank_top_k == 0 || self.rerank_top_k > 100 {
            return Err(ValidationError::new(
                "rerank_top_k",
                "rerank_top_k must be between 1 and 100",
            ));
        }

        if !(0.0..=1.0).contains(&self.min_score) {
            return Err(ValidationError::new(
                "min_score",
                "min_score must be between 0.0 and 1.0",
            ));
        }

        Ok(())
    }
}

/// Request body for multi-query retrieval.
///
/// Useful for complex queries that benefit from multiple query variations.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "utoipa", derive(utoipa::ToSchema))]
pub struct MultiQueryRequest {
    /// List of query strings (1-5 queries).
    pub queries: Vec<String>,

    /// Aggregation method: "max", "avg", or "rrf".
    #[serde(default = "default_aggregation")]
    pub aggregation: String,

    /// Number of results to return (1-100, default: 10).
    #[serde(default = "default_top_k")]
    pub top_k: usize,

    /// Additional metadata filters.
    #[serde(default)]
    pub filters: Option<serde_json::Value>,

    /// Whether to enable cross-encoder reranking.
    #[serde(default)]
    pub rerank: bool,
}

impl Default for MultiQueryRequest {
    fn default() -> Self {
        Self {
            queries: Vec::new(),
            aggregation: default_aggregation(),
            top_k: default_top_k(),
            filters: None,
            rerank: false,
        }
    }
}

impl MultiQueryRequest {
    /// Create a new multi-query request.
    #[must_use]
    pub fn new(queries: Vec<String>) -> Self {
        Self {
            queries,
            ..Default::default()
        }
    }

    /// Validate the request parameters.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - queries is empty or exceeds 5 queries
    /// - Any query is empty or exceeds 2000 characters
    /// - aggregation is not one of "max", "avg", "rrf"
    /// - top_k is 0 or exceeds 100
    pub fn validate(&self) -> Result<(), ValidationError> {
        if self.queries.is_empty() {
            return Err(ValidationError::new(
                "queries",
                "At least one query is required",
            ));
        }

        if self.queries.len() > 5 {
            return Err(ValidationError::new(
                "queries",
                "Cannot exceed 5 queries",
            ));
        }

        for (i, query) in self.queries.iter().enumerate() {
            if query.is_empty() {
                return Err(ValidationError::new(
                    "queries",
                    &format!("Query at index {} cannot be empty", i),
                ));
            }

            if query.len() > 2000 {
                return Err(ValidationError::new(
                    "queries",
                    &format!("Query at index {} cannot exceed 2000 characters", i),
                ));
            }
        }

        if !["max", "avg", "rrf"].contains(&self.aggregation.as_str()) {
            return Err(ValidationError::new(
                "aggregation",
                "aggregation must be one of: max, avg, rrf",
            ));
        }

        if self.top_k == 0 || self.top_k > 100 {
            return Err(ValidationError::new(
                "top_k",
                "top_k must be between 1 and 100",
            ));
        }

        Ok(())
    }
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

fn default_one() -> u32 {
    1
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

fn default_fusion_method() -> String {
    "rrf".to_string()
}

fn default_rrf_k() -> i32 {
    60
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

// Health types re-exported from rag-types for a canonical format across services.
pub use rag_types::{
    ComponentHealth, HealthResponse, LivenessResponse, ReadinessResponse,
};

/// Validation error for request parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationError {
    /// Field that failed validation.
    pub field: String,

    /// Error message.
    pub message: String,
}

impl ValidationError {
    /// Create a new validation error.
    #[must_use]
    pub fn new(field: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            field: field.into(),
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.field, self.message)
    }
}

impl std::error::Error for ValidationError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_retrieve_request_defaults() {
        let request = RetrieveRequest::new("test query");

        assert_eq!(request.query, "test query");
        assert_eq!(request.mode, SearchMode::Hybrid);
        assert_eq!(request.top_k, 10);
        assert!((request.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((request.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!(!request.rerank);
        assert_eq!(request.rerank_top_k, 20);
        assert!(request.filters.is_none());
        assert!((request.min_score - 0.0).abs() < f32::EPSILON);
        assert!(request.include_metadata);
        assert!(request.include_highlights);
    }

    #[test]
    fn test_retrieve_request_validation_valid() {
        let request = RetrieveRequest::new("test query");
        assert!(request.validate().is_ok());
    }

    #[test]
    fn test_retrieve_request_validation_empty_query() {
        let request = RetrieveRequest::new("");
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "query");
    }

    #[test]
    fn test_retrieve_request_validation_query_too_long() {
        let long_query = "a".repeat(2001);
        let request = RetrieveRequest::new(long_query);
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "query");
    }

    #[test]
    fn test_retrieve_request_validation_invalid_top_k() {
        let mut request = RetrieveRequest::new("test");
        request.top_k = 0;
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "top_k");

        request.top_k = 101;
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "top_k");
    }

    #[test]
    fn test_retrieve_request_validation_invalid_weights() {
        let mut request = RetrieveRequest::new("test");
        request.semantic_weight = 1.5;
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "semantic_weight");

        request.semantic_weight = 0.7;
        request.keyword_weight = -0.1;
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "keyword_weight");
    }

    #[test]
    fn test_multi_query_request_validation_valid() {
        let request = MultiQueryRequest::new(vec!["query1".into(), "query2".into()]);
        assert!(request.validate().is_ok());
    }

    #[test]
    fn test_multi_query_request_validation_empty() {
        let request = MultiQueryRequest::new(vec![]);
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "queries");
    }

    #[test]
    fn test_multi_query_request_validation_too_many() {
        let request = MultiQueryRequest::new(vec![
            "q1".into(),
            "q2".into(),
            "q3".into(),
            "q4".into(),
            "q5".into(),
            "q6".into(),
        ]);
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "queries");
    }

    #[test]
    fn test_multi_query_request_validation_invalid_aggregation() {
        let mut request = MultiQueryRequest::new(vec!["query".into()]);
        request.aggregation = "invalid".to_string();
        let err = request.validate().unwrap_err();
        assert_eq!(err.field, "aggregation");
    }

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

    #[test]
    fn test_validation_error_display() {
        let err = ValidationError::new("field", "message");
        assert_eq!(err.to_string(), "field: message");
    }
}
