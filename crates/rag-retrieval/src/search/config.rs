//! Configuration types for search operations.
//!
//! This module provides configuration structures for both semantic (vector)
//! and keyword (BM25) search operations.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;

/// Container for both semantic and keyword search configurations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchConfig {
    /// Configuration for semantic (vector) search.
    pub semantic: SemanticSearchConfig,

    /// Configuration for keyword (BM25) search.
    pub keyword: KeywordSearchConfig,
}

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            semantic: SemanticSearchConfig::default(),
            keyword: KeywordSearchConfig::default(),
        }
    }
}

impl SearchConfig {
    /// Create a new search config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the semantic search config.
    #[must_use]
    pub fn with_semantic(mut self, config: SemanticSearchConfig) -> Self {
        self.semantic = config;
        self
    }

    /// Set the keyword search config.
    #[must_use]
    pub fn with_keyword(mut self, config: KeywordSearchConfig) -> Self {
        self.keyword = config;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - Semantic: `QDRANT_URL`, `QDRANT_COLLECTION`, `SEMANTIC_TOP_K`, etc.
    /// - Keyword: `OPENSEARCH_URL`, `OPENSEARCH_INDEX`, `KEYWORD_TOP_K`, etc.
    #[must_use]
    pub fn from_env() -> Self {
        Self {
            semantic: SemanticSearchConfig::from_env(),
            keyword: KeywordSearchConfig::from_env(),
        }
    }
}

/// Configuration for semantic (vector) search using Qdrant.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticSearchConfig {
    /// Qdrant server URL.
    #[serde(default = "default_qdrant_url")]
    pub url: String,

    /// Collection name in Qdrant.
    #[serde(default = "default_collection")]
    pub collection: String,

    /// Number of top results to retrieve.
    #[serde(default = "default_top_k")]
    pub top_k: usize,

    /// Minimum score threshold (optional).
    /// Results below this score will be filtered out.
    #[serde(default)]
    pub score_threshold: Option<f32>,

    /// HNSW `ef_search` parameter for query accuracy vs speed tradeoff.
    /// Higher values improve recall but slow down search.
    #[serde(default = "default_ef_search")]
    pub ef_search: u64,

    /// Request timeout in milliseconds.
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,

    /// Whether to include payload in search results.
    #[serde(default = "default_with_payload")]
    pub with_payload: bool,
}

fn default_qdrant_url() -> String {
    "http://localhost:6333".into()
}

fn default_collection() -> String {
    "documents".into()
}

fn default_top_k() -> usize {
    50
}

fn default_ef_search() -> u64 {
    128
}

fn default_timeout_ms() -> u64 {
    10_000
}

fn default_with_payload() -> bool {
    true
}

impl Default for SemanticSearchConfig {
    fn default() -> Self {
        Self {
            url: default_qdrant_url(),
            collection: default_collection(),
            top_k: default_top_k(),
            score_threshold: None,
            ef_search: default_ef_search(),
            timeout_ms: default_timeout_ms(),
            with_payload: default_with_payload(),
        }
    }
}

impl SemanticSearchConfig {
    /// Create a new semantic search config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the Qdrant URL.
    #[must_use]
    pub fn with_url(mut self, url: impl Into<String>) -> Self {
        self.url = url.into();
        self
    }

    /// Set the collection name.
    #[must_use]
    pub fn with_collection(mut self, collection: impl Into<String>) -> Self {
        self.collection = collection.into();
        self
    }

    /// Set the number of top results to retrieve.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = top_k;
        self
    }

    /// Set the score threshold.
    #[must_use]
    pub const fn with_score_threshold(mut self, threshold: f32) -> Self {
        self.score_threshold = Some(threshold);
        self
    }

    /// Set the `ef_search` parameter.
    #[must_use]
    pub const fn with_ef_search(mut self, ef_search: u64) -> Self {
        self.ef_search = ef_search;
        self
    }

    /// Set the timeout in milliseconds.
    #[must_use]
    pub const fn with_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Set the timeout.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout_ms = timeout.as_millis() as u64;
        self
    }

    /// Set whether to include payload.
    #[must_use]
    pub const fn with_payload(mut self, with_payload: bool) -> Self {
        self.with_payload = with_payload;
        self
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `QDRANT_URL`: Server URL (default: `http://localhost:6333`)
    /// - `QDRANT_COLLECTION`: Collection name (default: `documents`)
    /// - `SEMANTIC_TOP_K`: Number of results (default: 50)
    /// - `SEMANTIC_SCORE_THRESHOLD`: Minimum score (optional)
    /// - `SEMANTIC_EF_SEARCH`: HNSW `ef_search` (default: 128)
    /// - `SEMANTIC_TIMEOUT_MS`: Timeout in milliseconds (default: 10000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(url) = std::env::var("QDRANT_URL") {
            config.url = url;
        }

        if let Ok(collection) = std::env::var("QDRANT_COLLECTION") {
            config.collection = collection;
        }

        if let Ok(top_k) = std::env::var("SEMANTIC_TOP_K") {
            if let Ok(k) = top_k.parse() {
                config.top_k = k;
            }
        }

        if let Ok(threshold) = std::env::var("SEMANTIC_SCORE_THRESHOLD") {
            if let Ok(t) = threshold.parse() {
                config.score_threshold = Some(t);
            }
        }

        if let Ok(ef) = std::env::var("SEMANTIC_EF_SEARCH") {
            if let Ok(e) = ef.parse() {
                config.ef_search = e;
            }
        }

        if let Ok(timeout) = std::env::var("SEMANTIC_TIMEOUT_MS") {
            if let Ok(t) = timeout.parse() {
                config.timeout_ms = t;
            }
        }

        config
    }
}

/// Configuration for keyword (BM25) search using `OpenSearch`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeywordSearchConfig {
    /// `OpenSearch` server URL.
    #[serde(default = "default_opensearch_url")]
    pub url: String,

    /// Index name in `OpenSearch`.
    #[serde(default = "default_index")]
    pub index: String,

    /// Fields to search in.
    #[serde(default = "default_fields")]
    pub fields: Vec<String>,

    /// Field boost weights.
    #[serde(default = "default_field_boosts")]
    pub field_boosts: HashMap<String, f32>,

    /// Number of top results to retrieve.
    #[serde(default = "default_top_k")]
    pub top_k: usize,

    /// Fuzziness setting for fuzzy matching.
    /// Use "AUTO", "0", "1", or "2".
    #[serde(default = "default_fuzziness")]
    pub fuzziness: String,

    /// Whether to include search highlights.
    #[serde(default = "default_highlight")]
    pub highlight: bool,

    /// Maximum fragment size for highlights.
    #[serde(default = "default_highlight_fragment_size")]
    pub highlight_fragment_size: usize,

    /// Request timeout in milliseconds.
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
}

fn default_opensearch_url() -> String {
    "http://localhost:9200".into()
}

fn default_index() -> String {
    "documents".into()
}

fn default_fields() -> Vec<String> {
    vec!["content".into(), "title".into()]
}

fn default_field_boosts() -> HashMap<String, f32> {
    let mut boosts = HashMap::new();
    boosts.insert("title".into(), 2.0);
    boosts
}

fn default_fuzziness() -> String {
    "AUTO".into()
}

fn default_highlight() -> bool {
    true
}

fn default_highlight_fragment_size() -> usize {
    150
}

impl Default for KeywordSearchConfig {
    fn default() -> Self {
        Self {
            url: default_opensearch_url(),
            index: default_index(),
            fields: default_fields(),
            field_boosts: default_field_boosts(),
            top_k: default_top_k(),
            fuzziness: default_fuzziness(),
            highlight: default_highlight(),
            highlight_fragment_size: default_highlight_fragment_size(),
            timeout_ms: default_timeout_ms(),
        }
    }
}

impl KeywordSearchConfig {
    /// Create a new keyword search config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the `OpenSearch` URL.
    #[must_use]
    pub fn with_url(mut self, url: impl Into<String>) -> Self {
        self.url = url.into();
        self
    }

    /// Set the index name.
    #[must_use]
    pub fn with_index(mut self, index: impl Into<String>) -> Self {
        self.index = index.into();
        self
    }

    /// Set the fields to search.
    #[must_use]
    pub fn with_fields(mut self, fields: Vec<String>) -> Self {
        self.fields = fields;
        self
    }

    /// Set field boost weights.
    #[must_use]
    pub fn with_field_boosts(mut self, boosts: HashMap<String, f32>) -> Self {
        self.field_boosts = boosts;
        self
    }

    /// Set the number of top results to retrieve.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = top_k;
        self
    }

    /// Set the fuzziness.
    #[must_use]
    pub fn with_fuzziness(mut self, fuzziness: impl Into<String>) -> Self {
        self.fuzziness = fuzziness.into();
        self
    }

    /// Set whether to include highlights.
    #[must_use]
    pub const fn with_highlight(mut self, highlight: bool) -> Self {
        self.highlight = highlight;
        self
    }

    /// Set the highlight fragment size.
    #[must_use]
    pub const fn with_highlight_fragment_size(mut self, size: usize) -> Self {
        self.highlight_fragment_size = size;
        self
    }

    /// Set the timeout in milliseconds.
    #[must_use]
    pub const fn with_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Set the timeout.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout_ms = timeout.as_millis() as u64;
        self
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `OPENSEARCH_URL`: Server URL (default: `http://localhost:9200`)
    /// - `OPENSEARCH_INDEX`: Index name (default: `documents`)
    /// - `KEYWORD_TOP_K`: Number of results (default: 50)
    /// - `KEYWORD_FUZZINESS`: Fuzziness setting (default: `AUTO`)
    /// - `KEYWORD_HIGHLIGHT`: Enable highlights (default: `true`)
    /// - `KEYWORD_TIMEOUT_MS`: Timeout in milliseconds (default: 10000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(url) = std::env::var("OPENSEARCH_URL") {
            config.url = url;
        }

        if let Ok(index) = std::env::var("OPENSEARCH_INDEX") {
            config.index = index;
        }

        if let Ok(top_k) = std::env::var("KEYWORD_TOP_K") {
            if let Ok(k) = top_k.parse() {
                config.top_k = k;
            }
        }

        if let Ok(fuzziness) = std::env::var("KEYWORD_FUZZINESS") {
            config.fuzziness = fuzziness;
        }

        if let Ok(highlight) = std::env::var("KEYWORD_HIGHLIGHT") {
            config.highlight = highlight.to_lowercase() == "true";
        }

        if let Ok(timeout) = std::env::var("KEYWORD_TIMEOUT_MS") {
            if let Ok(t) = timeout.parse() {
                config.timeout_ms = t;
            }
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_semantic_config_default() {
        let config = SemanticSearchConfig::default();
        assert_eq!(config.url, "http://localhost:6333");
        assert_eq!(config.collection, "documents");
        assert_eq!(config.top_k, 50);
        assert!(config.score_threshold.is_none());
        assert_eq!(config.ef_search, 128);
        assert_eq!(config.timeout_ms, 10_000);
        assert!(config.with_payload);
    }

    #[test]
    fn test_semantic_config_builder() {
        let config = SemanticSearchConfig::new()
            .with_url("http://qdrant:6333")
            .with_collection("my_docs")
            .with_top_k(100)
            .with_score_threshold(0.5)
            .with_ef_search(256)
            .with_timeout(Duration::from_secs(30))
            .with_payload(false);

        assert_eq!(config.url, "http://qdrant:6333");
        assert_eq!(config.collection, "my_docs");
        assert_eq!(config.top_k, 100);
        assert_eq!(config.score_threshold, Some(0.5));
        assert_eq!(config.ef_search, 256);
        assert_eq!(config.timeout_ms, 30_000);
        assert!(!config.with_payload);
    }

    #[test]
    fn test_keyword_config_default() {
        let config = KeywordSearchConfig::default();
        assert_eq!(config.url, "http://localhost:9200");
        assert_eq!(config.index, "documents");
        assert_eq!(config.fields, vec!["content", "title"]);
        assert_eq!(config.field_boosts.get("title"), Some(&2.0));
        assert_eq!(config.top_k, 50);
        assert_eq!(config.fuzziness, "AUTO");
        assert!(config.highlight);
        assert_eq!(config.highlight_fragment_size, 150);
        assert_eq!(config.timeout_ms, 10_000);
    }

    #[test]
    fn test_keyword_config_builder() {
        let mut boosts = HashMap::new();
        boosts.insert("content".into(), 1.5);

        let config = KeywordSearchConfig::new()
            .with_url("http://opensearch:9200")
            .with_index("chunks")
            .with_fields(vec!["body".into()])
            .with_field_boosts(boosts)
            .with_top_k(25)
            .with_fuzziness("1")
            .with_highlight(false)
            .with_highlight_fragment_size(200)
            .with_timeout(Duration::from_secs(5));

        assert_eq!(config.url, "http://opensearch:9200");
        assert_eq!(config.index, "chunks");
        assert_eq!(config.fields, vec!["body"]);
        assert_eq!(config.field_boosts.get("content"), Some(&1.5));
        assert_eq!(config.top_k, 25);
        assert_eq!(config.fuzziness, "1");
        assert!(!config.highlight);
        assert_eq!(config.highlight_fragment_size, 200);
        assert_eq!(config.timeout_ms, 5_000);
    }

    #[test]
    fn test_search_config() {
        let config = SearchConfig::new()
            .with_semantic(SemanticSearchConfig::new().with_top_k(100))
            .with_keyword(KeywordSearchConfig::new().with_top_k(50));

        assert_eq!(config.semantic.top_k, 100);
        assert_eq!(config.keyword.top_k, 50);
    }

    #[test]
    fn test_timeout_conversion() {
        let config = SemanticSearchConfig::new().with_timeout_ms(5000);
        assert_eq!(config.timeout(), Duration::from_millis(5000));

        let config = KeywordSearchConfig::new().with_timeout(Duration::from_secs(10));
        assert_eq!(config.timeout_ms, 10_000);
    }

    #[test]
    fn test_semantic_config_serialization() {
        let config = SemanticSearchConfig::new()
            .with_url("http://qdrant:6333")
            .with_score_threshold(0.75);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("qdrant:6333"));
        assert!(json.contains("0.75"));

        let deserialized: SemanticSearchConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.url, "http://qdrant:6333");
        assert_eq!(deserialized.score_threshold, Some(0.75));
    }

    #[test]
    fn test_keyword_config_serialization() {
        let config = KeywordSearchConfig::new()
            .with_index("my_index")
            .with_fuzziness("2");

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("my_index"));
        assert!(json.contains("\"2\""));

        let deserialized: KeywordSearchConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.index, "my_index");
        assert_eq!(deserialized.fuzziness, "2");
    }
}
