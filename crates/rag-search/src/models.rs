//! Data models for search operations.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// BM25 search request.
#[derive(Debug, Clone)]
pub struct BM25Request {
    /// Query text.
    pub query: String,
    /// Fields to search in.
    pub fields: Vec<String>,
    /// Maximum number of results.
    pub limit: usize,
    /// Offset for pagination.
    pub offset: usize,
    /// Filter conditions.
    pub filters: HashMap<String, Value>,
    /// Enable highlighting.
    pub highlight: bool,
    /// Highlight fields (defaults to search fields).
    pub highlight_fields: Vec<String>,
}

impl BM25Request {
    /// Create a new BM25 request.
    #[must_use]
    pub fn new(query: impl Into<String>) -> Self {
        Self {
            query: query.into(),
            fields: vec!["content".into()],
            limit: 10,
            offset: 0,
            filters: HashMap::new(),
            highlight: false,
            highlight_fields: Vec::new(),
        }
    }

    /// Set the search field.
    #[must_use]
    pub fn with_field(mut self, field: impl Into<String>) -> Self {
        self.fields = vec![field.into()];
        self
    }

    /// Set multiple search fields.
    #[must_use]
    pub fn with_fields(mut self, fields: Vec<String>) -> Self {
        self.fields = fields;
        self
    }

    /// Set the limit.
    #[must_use]
    pub const fn with_limit(mut self, limit: usize) -> Self {
        self.limit = limit;
        self
    }

    /// Set the offset.
    #[must_use]
    pub const fn with_offset(mut self, offset: usize) -> Self {
        self.offset = offset;
        self
    }

    /// Add a filter condition.
    #[must_use]
    pub fn with_filter(mut self, field: impl Into<String>, value: impl Into<Value>) -> Self {
        self.filters.insert(field.into(), value.into());
        self
    }

    /// Add a tenant filter.
    /// Uses `.keyword` subfield for exact matching on dynamically-mapped text fields.
    #[must_use]
    pub fn with_tenant(self, tenant_id: impl Into<String>) -> Self {
        self.with_filter("tenant_id.keyword", tenant_id.into())
    }

    /// Enable highlighting.
    #[must_use]
    pub fn with_highlight(mut self) -> Self {
        self.highlight = true;
        self
    }

    /// Set highlight fields.
    #[must_use]
    pub fn with_highlight_fields(mut self, fields: Vec<String>) -> Self {
        self.highlight = true;
        self.highlight_fields = fields;
        self
    }
}

/// Search response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    /// Search hits.
    pub hits: Vec<SearchHit>,
    /// Total number of matching documents.
    pub total: u64,
    /// Maximum score.
    pub max_score: Option<f64>,
    /// Time taken in milliseconds.
    pub took_ms: u64,
}

impl SearchResponse {
    /// Create a new search response.
    #[must_use]
    pub fn new(hits: Vec<SearchHit>, total: u64, took_ms: u64) -> Self {
        let max_score = hits.first().map(|h| h.score);
        Self {
            hits,
            total,
            max_score,
            took_ms,
        }
    }

    /// Get the number of hits.
    #[must_use]
    pub fn len(&self) -> usize {
        self.hits.len()
    }

    /// Check if results are empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.hits.is_empty()
    }

    /// Get document IDs.
    #[must_use]
    pub fn ids(&self) -> Vec<String> {
        self.hits.iter().map(|h| h.id.clone()).collect()
    }
}

/// A search hit.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    /// Document ID.
    pub id: String,
    /// Index name.
    pub index: String,
    /// Relevance score.
    pub score: f64,
    /// Document source.
    pub source: Value,
    /// Highlighted fragments.
    #[serde(default)]
    pub highlights: HashMap<String, Vec<String>>,
}

impl SearchHit {
    /// Create a new search hit.
    #[must_use]
    pub fn new(id: impl Into<String>, index: impl Into<String>, score: f64, source: Value) -> Self {
        Self {
            id: id.into(),
            index: index.into(),
            score,
            source,
            highlights: HashMap::new(),
        }
    }

    /// Set highlights.
    #[must_use]
    pub fn with_highlights(mut self, highlights: HashMap<String, Vec<String>>) -> Self {
        self.highlights = highlights;
        self
    }

    /// Get a field from the source.
    #[must_use]
    pub fn get_field(&self, field: &str) -> Option<&Value> {
        self.source.get(field)
    }

    /// Get a string field.
    #[must_use]
    pub fn get_string(&self, field: &str) -> Option<&str> {
        self.source.get(field).and_then(Value::as_str)
    }

    /// Get highlighted text for a field.
    #[must_use]
    pub fn get_highlight(&self, field: &str) -> Option<&[String]> {
        self.highlights.get(field).map(Vec::as_slice)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bm25_request_builder() {
        let request = BM25Request::new("test query")
            .with_fields(vec!["title".into(), "content".into()])
            .with_limit(20)
            .with_tenant("t-123")
            .with_highlight();

        assert_eq!(request.query, "test query");
        assert_eq!(request.fields.len(), 2);
        assert_eq!(request.limit, 20);
        assert!(request.highlight);
        assert!(request.filters.contains_key("tenant_id.keyword"));
    }

    #[test]
    fn test_search_hit() {
        let source = serde_json::json!({
            "content": "Hello world",
            "tenant_id": "t-123"
        });

        let hit = SearchHit::new("doc-1", "documents", 1.5, source);

        assert_eq!(hit.id, "doc-1");
        assert_eq!(hit.get_string("tenant_id"), Some("t-123"));
    }
}
