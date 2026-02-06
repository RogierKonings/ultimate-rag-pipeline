//! Configuration and types for the search pipeline.
//!
//! This module contains the pipeline configuration, per-request search options,
//! and the pipeline response type.

use serde::{Deserialize, Serialize};

use crate::acl::UnifiedFilter;
use crate::types::{RetrievalDebug, RetrievalMetrics, RetrievalResult};
use rag_types::SearchMode;

/// Configuration for the search pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineConfig {
    /// Whether to enable query expansion.
    #[serde(default)]
    pub enable_query_expansion: bool,

    /// Whether to enable HyDE (Hypothetical Document Embeddings).
    #[serde(default)]
    pub enable_hyde: bool,

    /// Whether to enable cross-encoder reranking.
    #[serde(default = "default_enable_reranking")]
    pub enable_reranking: bool,

    /// Whether to enable result caching.
    #[serde(default = "default_enable_caching")]
    pub enable_caching: bool,

    /// Number of results to pass to the reranker.
    #[serde(default = "default_rerank_top_k")]
    pub rerank_top_k: usize,

    /// Final number of results to return.
    #[serde(default = "default_final_top_k")]
    pub final_top_k: usize,

    /// Cache TTL in seconds.
    #[serde(default = "default_cache_ttl_secs")]
    pub cache_ttl_secs: u64,

    /// Total pipeline timeout in milliseconds.
    #[serde(default = "default_total_timeout_ms")]
    pub total_timeout_ms: u64,
}

fn default_enable_reranking() -> bool {
    true
}

fn default_enable_caching() -> bool {
    true
}

fn default_rerank_top_k() -> usize {
    20
}

fn default_final_top_k() -> usize {
    10
}

fn default_cache_ttl_secs() -> u64 {
    3600
}

fn default_total_timeout_ms() -> u64 {
    30000
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            enable_query_expansion: false,
            enable_hyde: false,
            enable_reranking: default_enable_reranking(),
            enable_caching: default_enable_caching(),
            rerank_top_k: default_rerank_top_k(),
            final_top_k: default_final_top_k(),
            cache_ttl_secs: default_cache_ttl_secs(),
            total_timeout_ms: default_total_timeout_ms(),
        }
    }
}

impl PipelineConfig {
    /// Create a new pipeline config with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Enable query expansion.
    #[must_use]
    pub const fn with_query_expansion(mut self, enable: bool) -> Self {
        self.enable_query_expansion = enable;
        self
    }

    /// Enable HyDE.
    #[must_use]
    pub const fn with_hyde(mut self, enable: bool) -> Self {
        self.enable_hyde = enable;
        self
    }

    /// Enable reranking.
    #[must_use]
    pub const fn with_reranking(mut self, enable: bool) -> Self {
        self.enable_reranking = enable;
        self
    }

    /// Enable caching.
    #[must_use]
    pub const fn with_caching(mut self, enable: bool) -> Self {
        self.enable_caching = enable;
        self
    }

    /// Set the rerank top-k.
    #[must_use]
    pub const fn with_rerank_top_k(mut self, top_k: usize) -> Self {
        self.rerank_top_k = top_k;
        self
    }

    /// Set the final top-k.
    #[must_use]
    pub const fn with_final_top_k(mut self, top_k: usize) -> Self {
        self.final_top_k = top_k;
        self
    }

    /// Set the cache TTL.
    #[must_use]
    pub const fn with_cache_ttl_secs(mut self, ttl: u64) -> Self {
        self.cache_ttl_secs = ttl;
        self
    }

    /// Set the total timeout.
    #[must_use]
    pub const fn with_total_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.total_timeout_ms = timeout_ms;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `PIPELINE_ENABLE_EXPANSION`: Enable query expansion (default: false)
    /// - `PIPELINE_ENABLE_HYDE`: Enable HyDE (default: false)
    /// - `PIPELINE_ENABLE_RERANKING`: Enable reranking (default: true)
    /// - `PIPELINE_ENABLE_CACHING`: Enable caching (default: true)
    /// - `PIPELINE_RERANK_TOP_K`: Rerank top-k (default: 20)
    /// - `PIPELINE_FINAL_TOP_K`: Final top-k (default: 10)
    /// - `PIPELINE_CACHE_TTL_SECS`: Cache TTL (default: 3600)
    /// - `PIPELINE_TOTAL_TIMEOUT_MS`: Total timeout (default: 30000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_EXPANSION") {
            config.enable_query_expansion = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_HYDE") {
            config.enable_hyde = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_RERANKING") {
            config.enable_reranking = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_CACHING") {
            config.enable_caching = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_RERANK_TOP_K") {
            if let Ok(v) = val.parse() {
                config.rerank_top_k = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_FINAL_TOP_K") {
            if let Ok(v) = val.parse() {
                config.final_top_k = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_CACHE_TTL_SECS") {
            if let Ok(v) = val.parse() {
                config.cache_ttl_secs = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_TOTAL_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.total_timeout_ms = v;
            }
        }

        config
    }
}

/// Options for a single search request.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchOptions {
    /// Override for number of results.
    #[serde(default)]
    pub top_k: Option<usize>,

    /// Search mode (hybrid, semantic, or keyword).
    #[serde(default)]
    pub search_mode: SearchMode,

    /// Additional filters to apply.
    #[serde(default)]
    pub additional_filters: Option<UnifiedFilter>,

    /// Whether to skip the cache for this request.
    #[serde(default)]
    pub skip_cache: bool,

    /// Override for reranking.
    #[serde(default)]
    pub rerank: Option<bool>,

    /// Override for HyDE.
    #[serde(default)]
    pub use_hyde: Option<bool>,

    /// Override for query expansion.
    #[serde(default)]
    pub expand_query: Option<bool>,
}

impl SearchOptions {
    /// Create new search options.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the top-k.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = Some(top_k);
        self
    }

    /// Set the search mode.
    #[must_use]
    pub const fn with_search_mode(mut self, mode: SearchMode) -> Self {
        self.search_mode = mode;
        self
    }

    /// Set additional filters.
    #[must_use]
    pub fn with_filters(mut self, filters: UnifiedFilter) -> Self {
        self.additional_filters = Some(filters);
        self
    }

    /// Skip the cache.
    #[must_use]
    pub const fn with_skip_cache(mut self, skip: bool) -> Self {
        self.skip_cache = skip;
        self
    }

    /// Override reranking.
    #[must_use]
    pub const fn with_rerank(mut self, rerank: bool) -> Self {
        self.rerank = Some(rerank);
        self
    }

    /// Override HyDE.
    #[must_use]
    pub const fn with_hyde(mut self, use_hyde: bool) -> Self {
        self.use_hyde = Some(use_hyde);
        self
    }

    /// Override query expansion.
    #[must_use]
    pub const fn with_expand_query(mut self, expand: bool) -> Self {
        self.expand_query = Some(expand);
        self
    }
}

/// Response from the search pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchPipelineResponse {
    /// The search results.
    pub results: Vec<RetrievalResult>,

    /// Timing and count metrics.
    pub metrics: RetrievalMetrics,

    /// Debug information about the search.
    pub debug: RetrievalDebug,
}

impl SearchPipelineResponse {
    /// Create a new response.
    #[must_use]
    pub fn new(results: Vec<RetrievalResult>, metrics: RetrievalMetrics, debug: RetrievalDebug) -> Self {
        Self {
            results,
            metrics,
            debug,
        }
    }

    /// Get the number of results.
    #[must_use]
    pub fn len(&self) -> usize {
        self.results.len()
    }

    /// Check if there are no results.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.results.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipeline_config_default() {
        let config = PipelineConfig::default();

        assert!(!config.enable_query_expansion);
        assert!(!config.enable_hyde);
        assert!(config.enable_reranking);
        assert!(config.enable_caching);
        assert_eq!(config.rerank_top_k, 20);
        assert_eq!(config.final_top_k, 10);
        assert_eq!(config.cache_ttl_secs, 3600);
        assert_eq!(config.total_timeout_ms, 30000);
    }

    #[test]
    fn test_pipeline_config_builder() {
        let config = PipelineConfig::new()
            .with_query_expansion(true)
            .with_hyde(true)
            .with_reranking(false)
            .with_caching(false)
            .with_rerank_top_k(30)
            .with_final_top_k(15)
            .with_cache_ttl_secs(7200)
            .with_total_timeout_ms(60000);

        assert!(config.enable_query_expansion);
        assert!(config.enable_hyde);
        assert!(!config.enable_reranking);
        assert!(!config.enable_caching);
        assert_eq!(config.rerank_top_k, 30);
        assert_eq!(config.final_top_k, 15);
        assert_eq!(config.cache_ttl_secs, 7200);
        assert_eq!(config.total_timeout_ms, 60000);
    }

    #[test]
    fn test_pipeline_config_from_env() {
        std::env::set_var("PIPELINE_ENABLE_EXPANSION", "true");
        std::env::set_var("PIPELINE_ENABLE_HYDE", "true");
        std::env::set_var("PIPELINE_RERANK_TOP_K", "25");
        std::env::set_var("PIPELINE_FINAL_TOP_K", "12");

        let config = PipelineConfig::from_env();

        assert!(config.enable_query_expansion);
        assert!(config.enable_hyde);
        assert_eq!(config.rerank_top_k, 25);
        assert_eq!(config.final_top_k, 12);

        // Clean up
        std::env::remove_var("PIPELINE_ENABLE_EXPANSION");
        std::env::remove_var("PIPELINE_ENABLE_HYDE");
        std::env::remove_var("PIPELINE_RERANK_TOP_K");
        std::env::remove_var("PIPELINE_FINAL_TOP_K");
    }

    #[test]
    fn test_search_options_default() {
        let options = SearchOptions::default();

        assert!(options.top_k.is_none());
        assert_eq!(options.search_mode, SearchMode::Hybrid);
        assert!(options.additional_filters.is_none());
        assert!(!options.skip_cache);
        assert!(options.rerank.is_none());
        assert!(options.use_hyde.is_none());
        assert!(options.expand_query.is_none());
    }

    #[test]
    fn test_search_options_builder() {
        let options = SearchOptions::new()
            .with_top_k(15)
            .with_search_mode(SearchMode::Semantic)
            .with_skip_cache(true)
            .with_rerank(false)
            .with_hyde(true)
            .with_expand_query(true);

        assert_eq!(options.top_k, Some(15));
        assert_eq!(options.search_mode, SearchMode::Semantic);
        assert!(options.skip_cache);
        assert_eq!(options.rerank, Some(false));
        assert_eq!(options.use_hyde, Some(true));
        assert_eq!(options.expand_query, Some(true));
    }

    #[test]
    fn test_search_pipeline_response() {
        let results = vec![RetrievalResult::new(
            "chunk_1".into(),
            "doc_1".into(),
            "Test content".into(),
            0.95,
        )];
        let metrics = RetrievalMetrics::new();
        let debug = RetrievalDebug::new();

        let response = SearchPipelineResponse::new(results, metrics, debug);

        assert_eq!(response.len(), 1);
        assert!(!response.is_empty());
    }

    #[test]
    fn test_pipeline_config_serialization() {
        let config = PipelineConfig::new()
            .with_rerank_top_k(25)
            .with_final_top_k(15);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"rerank_top_k\":25"));
        assert!(json.contains("\"final_top_k\":15"));

        let deserialized: PipelineConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.rerank_top_k, 25);
        assert_eq!(deserialized.final_top_k, 15);
    }
}
