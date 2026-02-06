//! API request types for the retrieval service.
//!
//! This module provides request types and validation for the HTTP API endpoints.

use serde::{Deserialize, Serialize};

use crate::SearchMode;

use super::validation::ValidationError;

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
}
