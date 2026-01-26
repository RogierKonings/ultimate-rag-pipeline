//! Data models for vector store operations.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// Search request parameters.
#[derive(Debug, Clone)]
pub struct SearchRequest {
    /// Query vector.
    pub vector: Vec<f32>,
    /// Maximum number of results.
    pub limit: u64,
    /// Score threshold (optional).
    pub score_threshold: Option<f32>,
    /// Filter conditions (optional).
    pub filter: Option<qdrant_client::qdrant::Filter>,
    /// Include payload in results.
    pub with_payload: bool,
    /// Include vector in results.
    pub with_vector: bool,
    /// Search parameters.
    pub params: Option<SearchParams>,
}

/// Search parameters for HNSW.
#[derive(Debug, Clone)]
pub struct SearchParams {
    /// Number of neighbors to consider during search.
    pub ef: Option<u64>,
    /// Enable exact search (slower but more accurate).
    pub exact: bool,
}

impl SearchRequest {
    /// Create a new search request.
    #[must_use]
    pub fn new(vector: Vec<f32>) -> Self {
        Self {
            vector,
            limit: 10,
            score_threshold: None,
            filter: None,
            with_payload: true,
            with_vector: false,
            params: None,
        }
    }

    /// Set the limit.
    #[must_use]
    pub const fn with_limit(mut self, limit: u64) -> Self {
        self.limit = limit;
        self
    }

    /// Set the score threshold.
    #[must_use]
    pub const fn with_score_threshold(mut self, threshold: f32) -> Self {
        self.score_threshold = Some(threshold);
        self
    }

    /// Set the filter.
    #[must_use]
    pub fn with_filter(mut self, filter: qdrant_client::qdrant::Filter) -> Self {
        self.filter = Some(filter);
        self
    }

    /// Include vectors in results.
    #[must_use]
    pub const fn with_vectors(mut self) -> Self {
        self.with_vector = true;
        self
    }

    /// Exclude payload from results.
    #[must_use]
    pub const fn without_payload(mut self) -> Self {
        self.with_payload = false;
        self
    }

    /// Set search parameters.
    #[must_use]
    pub fn with_params(mut self, params: SearchParams) -> Self {
        self.params = Some(params);
        self
    }
}

/// Search result.
#[derive(Debug, Clone)]
pub struct SearchResult {
    /// Scored points.
    pub points: Vec<ScoredPoint>,
    /// Search duration in milliseconds.
    pub duration_ms: Option<u64>,
}

impl SearchResult {
    /// Create a new search result.
    #[must_use]
    pub fn new(points: Vec<ScoredPoint>) -> Self {
        Self {
            points,
            duration_ms: None,
        }
    }

    /// Get the number of results.
    #[must_use]
    pub fn len(&self) -> usize {
        self.points.len()
    }

    /// Check if results are empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.points.is_empty()
    }

    /// Get point IDs.
    #[must_use]
    pub fn ids(&self) -> Vec<String> {
        self.points.iter().map(|p| p.id.clone()).collect()
    }
}

/// A point with its similarity score.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoredPoint {
    /// Point ID.
    pub id: String,
    /// Similarity score.
    pub score: f32,
    /// Payload (metadata).
    #[serde(default)]
    pub payload: HashMap<String, Value>,
    /// Vector (if requested).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vector: Option<Vec<f32>>,
}

impl ScoredPoint {
    /// Create a new scored point.
    #[must_use]
    pub fn new(id: impl Into<String>, score: f32) -> Self {
        Self {
            id: id.into(),
            score,
            payload: HashMap::new(),
            vector: None,
        }
    }

    /// Set the payload.
    #[must_use]
    pub fn with_payload(mut self, payload: HashMap<String, Value>) -> Self {
        self.payload = payload;
        self
    }

    /// Set the vector.
    #[must_use]
    pub fn with_vector(mut self, vector: Vec<f32>) -> Self {
        self.vector = Some(vector);
        self
    }

    /// Get a payload value.
    #[must_use]
    pub fn get_payload(&self, key: &str) -> Option<&Value> {
        self.payload.get(key)
    }

    /// Get a string payload value.
    #[must_use]
    pub fn get_string(&self, key: &str) -> Option<&str> {
        self.payload.get(key).and_then(Value::as_str)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_request_builder() {
        let request = SearchRequest::new(vec![0.1, 0.2, 0.3])
            .with_limit(20)
            .with_score_threshold(0.5)
            .with_vectors();

        assert_eq!(request.limit, 20);
        assert_eq!(request.score_threshold, Some(0.5));
        assert!(request.with_vector);
    }

    #[test]
    fn test_scored_point() {
        let mut payload = HashMap::new();
        payload.insert("tenant_id".into(), Value::String("t-1".into()));

        let point = ScoredPoint::new("doc-1", 0.95).with_payload(payload);

        assert_eq!(point.id, "doc-1");
        assert_eq!(point.score, 0.95);
        assert_eq!(point.get_string("tenant_id"), Some("t-1"));
    }
}
