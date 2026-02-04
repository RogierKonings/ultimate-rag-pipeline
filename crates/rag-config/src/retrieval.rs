//! Retrieval service configuration.

use crate::common::{EmbeddingConfig, OpenSearchConfig, QdrantConfig, RedisConfig, ServiceConfig};
use crate::timeouts::RetrievalTimeouts;
use serde::{Deserialize, Serialize};
use validator::Validate;

/// Full configuration for the retrieval service.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct RetrievalConfig {
    /// Base service configuration
    #[serde(flatten)]
    #[validate(nested)]
    pub service: ServiceConfig,

    /// Qdrant vector store configuration
    #[serde(default)]
    #[validate(nested)]
    pub qdrant: QdrantConfig,

    /// `OpenSearch` configuration
    #[serde(default)]
    #[validate(nested)]
    pub opensearch: OpenSearchConfig,

    /// Redis cache configuration
    #[serde(default)]
    #[validate(nested)]
    pub redis: Option<RedisConfig>,

    /// Embedding service configuration
    #[serde(default)]
    #[validate(nested)]
    pub embedding: EmbeddingConfig,

    /// Timeout configuration
    #[serde(default)]
    #[validate(nested)]
    pub timeouts: RetrievalTimeouts,

    /// Search configuration
    #[serde(default)]
    #[validate(nested)]
    pub search: SearchConfig,

    /// Reranker configuration
    #[serde(default)]
    #[validate(nested)]
    pub reranker: RerankerConfig,

    /// Feature flags
    #[serde(default)]
    pub features: RetrievalFeatures,
}

impl Default for RetrievalConfig {
    fn default() -> Self {
        Self {
            service: ServiceConfig {
                port: 8002,
                service_name: "retrieval-service".to_string(),
                ..Default::default()
            },
            qdrant: QdrantConfig::default(),
            opensearch: OpenSearchConfig::default(),
            redis: None,
            embedding: EmbeddingConfig::default(),
            timeouts: RetrievalTimeouts::default(),
            search: SearchConfig::default(),
            reranker: RerankerConfig::default(),
            features: RetrievalFeatures::default(),
        }
    }
}

/// Search algorithm configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct SearchConfig {
    /// Default number of results to return
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_top_k")]
    pub default_top_k: u32,

    /// Number of candidates to retrieve before fusion
    #[validate(range(min = 10, max = 500))]
    #[serde(default = "default_candidate_count")]
    pub candidate_count: u32,

    /// Default semantic search weight (0.0-1.0)
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,

    /// Default keyword search weight (0.0-1.0)
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,

    /// RRF constant k
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_rrf_k")]
    pub rrf_k: u32,

    /// Minimum score threshold
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default)]
    pub min_score: f32,

    /// BGE instruction prefix for queries
    #[serde(default = "default_query_prefix")]
    pub query_prefix: String,
}

const fn default_top_k() -> u32 {
    10
}

const fn default_candidate_count() -> u32 {
    50
}

const fn default_semantic_weight() -> f32 {
    0.7
}

const fn default_keyword_weight() -> f32 {
    0.3
}

const fn default_rrf_k() -> u32 {
    60
}

fn default_query_prefix() -> String {
    "Represent this sentence for searching relevant passages: ".to_string()
}

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            default_top_k: default_top_k(),
            candidate_count: default_candidate_count(),
            semantic_weight: default_semantic_weight(),
            keyword_weight: default_keyword_weight(),
            rrf_k: default_rrf_k(),
            min_score: 0.0,
            query_prefix: default_query_prefix(),
        }
    }
}

/// Reranker configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct RerankerConfig {
    /// Reranker service URL
    #[serde(default = "default_reranker_url")]
    pub url: String,

    /// Model name
    #[serde(default = "default_reranker_model")]
    pub model: String,

    /// Batch size for reranking
    #[validate(range(min = 1, max = 64))]
    #[serde(default = "default_reranker_batch_size")]
    pub batch_size: u32,

    /// Number of candidates to rerank
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_rerank_top_k")]
    pub rerank_top_k: u32,

    /// Enable reranking by default
    #[serde(default)]
    pub enabled: bool,
}

fn default_reranker_url() -> String {
    "http://localhost:8085".to_string()
}

fn default_reranker_model() -> String {
    "BAAI/bge-reranker-v2-m3".to_string()
}

const fn default_reranker_batch_size() -> u32 {
    32
}

const fn default_rerank_top_k() -> u32 {
    20
}

impl Default for RerankerConfig {
    fn default() -> Self {
        Self {
            url: default_reranker_url(),
            model: default_reranker_model(),
            batch_size: default_reranker_batch_size(),
            rerank_top_k: default_rerank_top_k(),
            enabled: false,
        }
    }
}

/// Feature flags for the retrieval service.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[allow(clippy::struct_excessive_bools)] // Feature flags are naturally boolean
pub struct RetrievalFeatures {
    /// Enable query caching
    #[serde(default)]
    pub cache_enabled: bool,

    /// Enable embedding caching
    #[serde(default = "default_true")]
    pub embedding_cache_enabled: bool,

    /// Enable debug output in responses
    #[serde(default)]
    pub debug_enabled: bool,

    /// Enable metrics collection
    #[serde(default = "default_true")]
    pub metrics_enabled: bool,

    /// Enable OpenTelemetry tracing
    #[serde(default)]
    pub tracing_enabled: bool,

    /// Enable graceful degradation
    #[serde(default = "default_true")]
    pub degradation_enabled: bool,
}

const fn default_true() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_retrieval_config_default() {
        let config = RetrievalConfig::default();
        assert_eq!(config.service.port, 8002);
        assert_eq!(config.search.rrf_k, 60);
        assert!((config.search.semantic_weight - 0.7).abs() < f32::EPSILON);
    }

    #[test]
    fn test_search_config_default() {
        let config = SearchConfig::default();
        assert_eq!(config.default_top_k, 10);
        assert_eq!(config.candidate_count, 50);
    }

    #[test]
    fn test_reranker_config_default() {
        let config = RerankerConfig::default();
        assert_eq!(config.rerank_top_k, 20);
        assert!(!config.enabled);
    }
}
